"""Translation and reviewed-document publishing, independent of the GUI."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, urlparse

from ui_translations import tr
from task_runtime import cancellable_call
from model_budget import (BudgetExceeded, ResponseTooLong, budget_chunks, check_request,
                          effective_limits, input_budget, messages, request_size)

try:
    import requests
except ImportError:
    requests = None


PROVIDERS = {
    "DeepSeek": "https://api.deepseek.com/v1",
    "Kimi / Moonshot": "https://api.moonshot.cn/v1",
    "Doubao / 火山方舟": "https://ark.cn-beijing.volces.com/api/v3",
    "自定义 OpenAI compatible": "",
}
# Common PaddleOCR language codes. Editable selectors also accept other model languages.
LANGUAGES = {
    "简体中文 (ch)": "Simplified Chinese", "繁体中文 (chinese_cht)": "Traditional Chinese",
    "英语 (en)": "English", "日语 (japan)": "Japanese", "韩语 (korean)": "Korean",
    "法语 (fr)": "French", "德语 (german)": "German", "西班牙语 (es)": "Spanish",
    "葡萄牙语 (pt)": "Portuguese", "意大利语 (it)": "Italian", "俄语 (ru)": "Russian",
    "阿拉伯语 (ar)": "Arabic", "印地语 (hi)": "Hindi", "泰语 (th)": "Thai",
    "越南语 (vi)": "Vietnamese", "印尼语 (id)": "Indonesian", "土耳其语 (tr)": "Turkish",
    "波兰语 (pl)": "Polish", "荷兰语 (nl)": "Dutch", "乌克兰语 (uk)": "Ukrainian",
    "希腊语 (el)": "Greek", "希伯来语 (he)": "Hebrew", "波斯语 (fa)": "Persian",
    "马来语 (ms)": "Malay", "瑞典语 (sv)": "Swedish", "捷克语 (cs)": "Czech",
    "罗马尼亚语 (ro)": "Romanian", "芬兰语 (fi)": "Finnish", "丹麦语 (da)": "Danish",
    "挪威语 (no)": "Norwegian", "匈牙利语 (hu)": "Hungarian",
}


class ProcessingCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelProfile:
    base_url: str = PROVIDERS["DeepSeek"]
    api_key: str = field(default="", repr=False)
    model: str = ""
    input_limit: int = 0
    context_limit: int = 0
    output_limit: int = 0
    limit_source: str = "fallback"

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise ValueError(tr('请填写有效的 OpenAI compatible Base URL。'))
        if not self.api_key.strip() or not self.model.strip():
            raise ValueError(tr('请填写 API Key，并拉取或手动输入模型名称。'))
        for value in (self.input_limit, self.context_limit, self.output_limit):
            if type(value) is not int or value < 0:
                raise ValueError(tr("模型 token 上限须为正整数。"))


def _cancel(stop: Callable[[], bool]) -> None:
    if stop():
        raise ProcessingCancelled(tr('用户已停止文献处理。'))


def chat(profile: ModelProfile, instruction: str, data: dict, stop=lambda: False, input_percent=50) -> str:
    profile.validate()
    _cancel(stop)
    check_request(profile, instruction, data, input_percent)
    if requests is None:
        raise RuntimeError(tr('缺少 requests，请先安装 requirements.txt。'))
    body = {"model": profile.model.strip(), "messages": messages(instruction, data)}
    limits = effective_limits(profile)
    known_deepseek = (urlparse(profile.base_url).hostname == "api.deepseek.com"
                      and profile.model.lower() in {"deepseek-flash", "deepseek-v4.1-flash", "deepseek-v4-pro"})
    # Avoid a small server default truncating a large translation. Do not impose
    # DeepSeek's output parameter/limit on an unrelated compatible deployment.
    if limits.output_limit and (profile.output_limit or known_deepseek):
        available = limits.context_limit - request_size(instruction, data) - 256 if limits.context_limit else limits.output_limit
        body["max_tokens"] = min(limits.output_limit, max(1, available))
    def request():
        response = requests.post(
            profile.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {profile.api_key.strip()}", "Content-Type": "application/json"},
            json=body, timeout=(15, 300),
        )
        try:
            if not response.ok:
                # Avoid reflecting server bodies that may contain credentials or document contents.
                raise RuntimeError(tr('大模型请求失败：HTTP {arg0}。请检查接口、模型、额度和网络。', arg0=response.status_code))
            try:
                choice = response.json()["choices"][0]
                content = choice["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError(tr('大模型响应缺少 choices[0].message.content。')) from exc
            if choice.get("finish_reason") == "length":
                raise ResponseTooLong(tr('大模型输出被截断或过滤，请减小分段长度或更换模型。'))
            if choice.get("finish_reason") == "content_filter":
                raise RuntimeError(tr('大模型输出被截断或过滤，请减小分段长度或更换模型。'))
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(tr('大模型返回空文本。'))
            return content.strip()

        finally:
            response.close()
    return cancellable_call(request, stop, cancelled=ProcessingCancelled)


def json_reply(content: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
    except ValueError as exc:
        raise RuntimeError(tr('大模型没有返回有效 JSON，请重试或更换模型。')) from exc
    if not isinstance(value, dict):
        raise RuntimeError(tr('大模型必须返回 JSON 对象。'))
    return value


def review_reply(content: str) -> dict:
    value = json_reply(content)
    if type(value.get("has_problem")) is not bool:
        raise RuntimeError(tr('核验结果缺少布尔字段 has_problem；不能视为核验通过。'))
    return value


def detect_language(text: str, target: str, profile: ModelProfile, stop=lambda: False, input_percent=50) -> dict:
    if not text.strip():
        raise ValueError(tr('文献为空，无法识别语言。'))
    result = json_reply(chat(profile,
        '识别 sample 的主要自然语言，判断是否属于 target_language（区分简繁中文）。'
        '只返回 JSON：{"language":"语言名称或 unknown","is_target_language":true或false}。'
        '忽略 Markdown 标记、链接和代码；没有足够自然语言时返回 unknown。',
        {"sample": text[:300], "target_language": LANGUAGES.get(target, target)}, stop, input_percent=input_percent))
    if (not isinstance(result.get("language"), str) or not result["language"].strip()
            or result["language"].strip().lower() in {"unknown", "und", "未知"}
            or type(result.get("is_target_language")) is not bool):
        raise RuntimeError(tr('前 300 字符不足以可靠识别语言；请检查文献开头后重试。'))
    return result


def translated_path(source: Path, input_root: Path, output_root: Path | None, prefix=False) -> Path:
    name = f"TRANSLATED_{source.stem}.md" if prefix else f"{source.stem}_TRANSLATED.md"
    parent = source.parent if output_root is None else output_root / source.relative_to(input_root).parent
    result = parent / name
    if result.resolve() == source.resolve():
        raise ValueError(tr('译文路径不能覆盖原文。'))
    return result


def find_markdown_files(root: Path, recursive=True, output_root: Path | None = None) -> list[Path]:
    output = output_root.resolve() if output_root else None
    root = root.resolve()
    paths = root.rglob("*") if recursive else root.iterdir()
    result = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".md" or path.is_symlink():
            continue
        if (path.stem.upper().startswith(("TRANSLATED_", "FORMATTED_"))
                or path.stem.upper().endswith(("_TRANSLATED", "_FORMATTED"))):
            continue
        # Only exclude a distinct output subtree, never the input folder itself.
        if output and output != root and output in path.resolve().parents:
            continue
        result.append(path)
    return sorted(result)


@dataclass
class TranslationOptions:
    target: str = "简体中文 (ch)"
    source: str = "自动检测"
    secondary_review: bool = False
    proofreading: bool = False
    arbitration: str = "用户自行裁决"
    input_percent: int = 50
    allow_arbiter_revision: bool = False
    force_auto: bool = False


TRANSLATE_PROMPT = ("你是学术文献翻译员。把 source 全文忠实译成 target_language；"
    "保留全部事实、数字、引用、公式、代码块、图片和链接地址以及 Markdown 结构。"
    "不要摘要、增删内容或添加说明；专名与参考文献保持可识别。只返回译文 Markdown，勿套额外代码围栏。")
COMPARE_PROMPT = ('比较原文 source 与两份译文 first、second，检查准确性、遗漏、误译、数字和引文。'
    '只返回 JSON：{"has_problem":true或false,"issues":["具体问题"],'
    '"summary":"结论"}。两份译文均忠实准确时 has_problem=false。')
ARBITRATE_PROMPT = ('核对原文及两份译文并裁决。只返回 JSON：'
    '{"choice":"first|second|unresolved","has_problem":true或false,"reason":"理由"}。'
    'has_problem 表示所选译文是否仍有问题，而不是是否存在分歧。'
    '只有所选译文完整准确时 has_problem=false；两份都有问题时 choice=unresolved。')
PROOFREAD_PROMPT = ('校对译文，结合 source 检查语句不通、缺字少字、漏译等问题，不改写或润色。'
    '只返回 JSON：{"has_problem":true或false,"issues":["具体问题"],"summary":"结论"}。')
PROOF_ARBITRATE_PROMPT = ('对照原文 source、最终译文 translation，独立复核 proofreading 中的疑点。'
    '判断疑点是否真实存在，不以另一模型的判断为结论，不改写译文。只返回 JSON：'
    '{"decision":"approve|needs_review|unresolved","has_problem":true或false,"reason":"具体理由"}。'
    '只有确认最终译文完整准确、校对疑点均不成立时，返回 decision=approve 且 has_problem=false；'
    '确认仍有问题时 decision=needs_review 且 has_problem=true；证据不足时 decision=unresolved。')
ARBITRATE_REVISE_PROMPT = ('对照原文 source、两份译文 first、second 及 comparison，独立裁决。'
    '用户已授权你直接修订译文。已有完整准确的译文可选 first 或 second；两份都有可修复错误时，'
    '可选 revised 并提供完整修订译文，修复误译、遗漏或缺字，不摘要、不润色，不编造原文没有的信息。'
    '保留全部事实、数字、引文、公式、代码、图片与链接及 Markdown 结构。无法可靠修复时选 unresolved。'
    '只返回 JSON：{"choice":"first|second|revised|unresolved","has_problem":true或false,'
    '"reason":"理由","revised_translation":"仅 revised 时必填的完整修订译文"}。'
    '只有所选或修订译文完整准确时 has_problem=false。')
PROOF_REVISE_PROMPT = ('对照原文 source、译文 translation 和 proofreading，独立复核疑点。'
    '用户已授权直接修订译文；疑点不成立时 approve，确有且能可靠修复时 revised 并返回完整修订译文。'
    '只修复误译、缺字少字、语句不通及遗漏，不摘要、不润色、不补写不确定的原文内容。'
    '保留事实、数字、引文、公式、代码、图片与链接及 Markdown 结构。无法确定时 unresolved。'
    '只返回 JSON：{"decision":"approve|revised|needs_review|unresolved","has_problem":true或false,'
    '"reason":"理由","revised_translation":"仅 revised 时必填的完整修订译文"}。'
    '只有译文或修订稿完整准确时 has_problem=false。')
REVISION_VERIFY_PROMPT = ('独立核验 source 与 translation。translation 是裁决模型修订后的完整译文。'
    '检查是否忠实完整、无误译遗漏或缺字、语句通顺，保留事实、数字、引文、公式、代码、图片、链接和 Markdown。'
    '只核验，不再次修订，不以裁决模型结论代替判断。只返回 JSON：'
    '{"has_problem":true或false,"issues":["具体问题"],"summary":"结论"}。'
    '只有完整准确且没有任何疑点时 has_problem=false 且 issues=[]。')


class _RetryChunk(Exception):
    """An explicit user request to discard the current generated drafts."""


def translate_document(source: Path, destination: Path, options: TranslationOptions,
                       translator: ModelProfile, reviewer: ModelProfile | None = None,
                       proofreader: ModelProfile | None = None, arbiter: ModelProfile | None = None,
                       decide=None, stop=lambda: False, log=lambda message: None) -> dict:
    """Return an auditable result. Unresolved documents are saved but never approved."""
    if options.force_auto:
        options = replace(options, arbitration="大模型裁决", allow_arbiter_revision=True, proofreading=True)
        decide = None
    if destination.resolve() == source.resolve():
        raise ValueError(tr('译文不能覆盖原文。'))
    if destination.exists():
        return {"status": "existing", "path": str(destination), "verified": False}
    if not options.target.strip():
        raise ValueError(tr('目标语言不能为空。'))
    if options.secondary_review and reviewer is None:
        raise ValueError(tr('二次翻译核对需要指定模型。'))
    if options.proofreading and proofreader is None:
        raise ValueError(tr('文本校对需要指定模型。'))
    model_arbitration = (options.secondary_review or options.proofreading) and options.arbitration == "大模型裁决"
    if model_arbitration and arbiter is None:
        raise ValueError(tr('请选择裁决模型。'))
    revision_authorized = model_arbitration and options.allow_arbiter_revision is True
    arbitration_prompt = ARBITRATE_REVISE_PROMPT if revision_authorized else ARBITRATE_PROMPT
    proof_arbitration_prompt = PROOF_REVISE_PROMPT if revision_authorized else PROOF_ARBITRATE_PROMPT
    percent = options.input_percent
    active = {"translator": translator}
    if options.secondary_review:
        active["reviewer"] = reviewer
    if options.proofreading:
        active["proofreader"] = proofreader
    if model_arbitration:
        active["arbiter"] = arbiter
    log(tr("翻译检查设置：二次核对 {arg0}；文本校对 {arg1}；问题处理 {arg2}；裁决模型 {arg3}。",
           arg0=tr("启用") if options.secondary_review else tr("未启用"),
           arg1=tr("启用") if options.proofreading else tr("未启用"),
           arg2=tr(options.arbitration) if options.secondary_review or options.proofreading else tr("未启用"),
           arg3=arbiter.model if model_arbitration else tr("未启用")))
    log(tr("裁决模型直接修订授权：{arg0}。", arg0=tr("启用") if revision_authorized else tr("未启用")))
    for role, profile in active.items():
        profile.validate()
        log(tr("{arg0} / {arg1}：输入预算 {arg2} tokens；比例 {arg3}%；来源 {arg4}。",
               arg0=role, arg1=profile.model, arg2=input_budget(profile, percent), arg3=percent,
               arg4=tr({"api": "接口元数据", "manual": "手动设置", "fallback": "DeepSeek-V4.1-Flash 默认值"}.get(
                   effective_limits(profile).limit_source, "手动设置"))))

    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8-sig")
    language = detect_language(text, options.target, translator, stop, input_percent=percent)
    if language["is_target_language"]:
        return {"status": "target_language", "language": language["language"], "verified": False}
    source_language = language["language"] if options.source == "自动检测" else LANGUAGES.get(options.source, options.source)
    records, translated = [], []

    def data_for(original):
        return {"source": original, "source_language": source_language,
                "target_language": LANGUAGES.get(options.target, options.target)}

    def ask(profile, prompt, data):
        _cancel(stop)
        check_request(profile, prompt, data, percent)
        return chat(profile, prompt, data, stop, input_percent=percent)

    def revise(verdict, before, original, stage, record):
        candidate = verdict.get("revised_translation")
        revision = {"stage": stage, "before": before,
                    "candidate": candidate if isinstance(candidate, str) else None, "accepted": False}
        record.setdefault("revisions", []).append(revision)
        if not isinstance(candidate, str) or not candidate.strip():
            revision["error"] = str(tr("裁决模型未提供有效的完整修订稿。"))
            return before, revision
        candidate = revision["candidate"] = candidate.strip()
        verifier = reviewer if stage == "translation" else proofreader
        log(tr("{arg0}：第 {arg1} 段已生成模型修订稿，正在自动核验。", arg0=source.name, arg1=record["chunk"]))
        try:
            verification = review_reply(ask(verifier, REVISION_VERIFY_PROMPT,
                                            {**data_for(original), "translation": candidate}))
            revision["verification"] = verification
            revision["verifier"] = verifier.model
            if (not isinstance(verification.get("issues"), list)
                    or not all(isinstance(issue, str) for issue in verification["issues"])):
                raise RuntimeError(tr("修订稿核验缺少有效的问题列表，不能自动接受。"))
            revision["accepted"] = not verification["has_problem"] and not any(issue.strip() for issue in verification["issues"])
        except (ProcessingCancelled, BudgetExceeded, ResponseTooLong):
            raise
        except Exception as exc:
            revision["error"] = str(exc)
        log(tr("{arg0}：第 {arg1} 段修订稿核验结果：{arg2}。", arg0=source.name, arg1=record["chunk"],
               arg2=tr("已自动接受修订稿") if revision["accepted"] else tr("修订稿仍需处理")))
        return (candidate if revision["accepted"] else before), revision

    def fits(original):
        _cancel(stop)
        data = data_for(original)
        try:
            check_request(translator, TRANSLATE_PROMPT, data, percent)
            # Plan for expanded translations and every enabled downstream model.
            # Actual responses are checked again; excessive expansion triggers
            # a smaller source chunk and a complete new translation/review.
            candidates = {**data, "first": original * 2, "second": original * 2}
            report_reserve = " " * min(4096, max(128, input_budget(arbiter, percent) // 8)) if model_arbitration else ""
            if options.secondary_review:
                check_request(reviewer, TRANSLATE_PROMPT, data, percent)
                check_request(reviewer, COMPARE_PROMPT, candidates, percent)
                if options.arbitration == "大模型裁决":
                    check_request(arbiter, arbitration_prompt,
                                  {**candidates, "comparison": report_reserve}, percent)
                    if revision_authorized:
                        check_request(reviewer, REVISION_VERIFY_PROMPT, {**data, "translation": original * 2}, percent)
            if options.proofreading:
                check_request(proofreader, PROOFREAD_PROMPT, {**data, "translation": original * 2}, percent)
                if model_arbitration:
                    check_request(arbiter, proof_arbitration_prompt,
                                  {**data, "translation": original * 2, "proofreading": report_reserve}, percent)
                    if revision_authorized:
                        check_request(proofreader, REVISION_VERIFY_PROMPT, {**data, "translation": original * 2}, percent)
            return True
        except BudgetExceeded:
            return False

    chunks = budget_chunks(text, fits)
    attempt_drafts = {}
    attempt_record = {}
    def translate_chunk(original, index):
        data = data_for(original)
        first = ask(translator, TRANSLATE_PROMPT, data)
        attempt_drafts["first"] = first
        record = attempt_record
        record.update(chunk=index, verified=True, pendingReasons=[])
        if options.secondary_review:
            log(tr('{arg0}：第 {arg1} 段二次翻译核对', arg0=source.name, arg1=index))
            second = ask(reviewer, TRANSLATE_PROMPT, data)
            attempt_drafts["second"] = second
            record["candidates"] = {"first": first, "second": second}
            comparison = review_reply(ask(reviewer, COMPARE_PROMPT,
                {**data, "first": first, "second": second}))
            record["comparison"] = comparison
            if comparison["has_problem"]:
                revision = None
                if options.arbitration == "大模型裁决":
                    log(tr("{arg0}：第 {arg1} 段开始翻译分歧裁决，模型 {arg2}。",
                           arg0=source.name, arg1=index, arg2=arbiter.model))
                    verdict = review_reply(ask(arbiter, arbitration_prompt,
                        {**data, "first": first, "second": second, "comparison": comparison}))
                    raw_choice = verdict.get("choice")
                    raw_choice = raw_choice.strip().lower() if isinstance(raw_choice, str) else "unresolved"
                    choice = raw_choice if raw_choice in {"first", "second"} and not verdict["has_problem"] else "unresolved"
                    if revision_authorized and raw_choice == "revised" and not verdict["has_problem"]:
                        first, revision = revise(verdict, first, original, "translation", record)
                        choice = "revised" if revision["accepted"] else "unresolved"
                    record["arbitration"] = verdict
                    record["arbitrationChoice"] = choice
                    log(tr("{arg0}：第 {arg1} 段翻译裁决结果：{arg2}；理由：{arg3}",
                           arg0=source.name, arg1=index,
                           arg2=tr({"first": "接受首次译文", "second": "接受二次译文", "revised": "已自动接受修订稿", "unresolved": "未能明确批准译文"}[choice]),
                           arg3=verdict.get("reason") or tr("模型未提供理由")))
                else:
                    log(tr("{arg0}：第 {arg1} 段翻译有分歧，等待用户裁决。", arg0=source.name, arg1=index))
                    choice = decide({"filename": source.name, "chunk": index, "source": original,
                                     "first": first, "second": second, "comparison": comparison}) if decide else "unresolved"
                    record["arbitration"] = {"choice": choice, "by": "user"}
                if options.arbitration == "大模型裁决" and choice == "unresolved" and decide:
                    drafts = {"first": first, "second": second}
                    if revision and revision.get("candidate"):
                        drafts["second"] = revision["candidate"]
                    choice = decide({"filename": source.name, "chunk": index, "source": original,
                        **drafts, "problem": {"comparison": comparison, "arbitration": verdict, "revision": revision}})
                    record["userDecision"] = choice
                if choice == "retry":
                    raise _RetryChunk()
                # Keeping a disputed draft is not a positive quality approval.
                if options.arbitration != "大模型裁决" or "userDecision" in record:
                    record["verified"] = False
                    record["pendingReasons"].append("translation_dispute_unresolved")
                if choice == "second":
                    first = revision["candidate"] if revision and revision.get("candidate") else second
                elif choice not in {"first", "revised"}:
                    record["verified"] = False
                    if "translation_dispute_unresolved" not in record["pendingReasons"]:
                        record["pendingReasons"].append("translation_dispute_unresolved")
        if options.proofreading:
            revision = None
            if any(item["accepted"] for item in record.get("revisions", [])):
                attempt_drafts["first"] = first
            log(tr('{arg0}：第 {arg1} 段文本校对', arg0=source.name, arg1=index))
            proof = review_reply(ask(proofreader, PROOFREAD_PROMPT, {**data, "translation": first}))
            record["proofreading"] = proof
            proof_passed = not proof["has_problem"]
            if not proof_passed and model_arbitration:
                log(tr("{arg0}：第 {arg1} 段开始校对疑点裁决，模型 {arg2}。",
                       arg0=source.name, arg1=index, arg2=arbiter.model))
                verdict = review_reply(ask(arbiter, proof_arbitration_prompt,
                    {**data, "translation": first, "proofreading": proof}))
                proof_passed = verdict.get("decision") == "approve" and not verdict["has_problem"]
                if revision_authorized and verdict.get("decision") == "revised" and not verdict["has_problem"]:
                    first, revision = revise(verdict, first, original, "proofreading", record)
                    proof_passed = revision["accepted"]
                record["proofreadingArbitration"] = verdict
                log(tr("{arg0}：第 {arg1} 段校对裁决结果：{arg2}；理由：{arg3}",
                       arg0=source.name, arg1=index,
                       arg2=tr("校对疑点已排除") if proof_passed else tr("校对疑点尚未解决"),
                       arg3=verdict.get("reason") or tr("模型未提供理由")))
            if not proof_passed:
                record["pendingReasons"].append("proofreading_problem")
                log(tr("{arg0}：第 {arg1} 段校对疑点尚未解决，本段保持待处理。", arg0=source.name, arg1=index))
                if decide:
                    drafts = dict(attempt_drafts)
                    if revision and revision.get("candidate"):
                        drafts = {"first": first, "second": revision["candidate"]}
                    choice = decide({"filename": source.name, "chunk": index, "source": original,
                        **drafts, "problem": {"proofreading": proof, "arbitration": record.get("proofreadingArbitration"), "revision": revision}})
                    if choice == "retry":
                        raise _RetryChunk()
                    if choice in drafts:
                        first = drafts[choice]
                    record["proofreadingUserDecision"] = choice
            record["verified"] = record["verified"] and proof_passed
        return first, record

    position = 0
    while position < len(chunks):
        _cancel(stop)
        original = chunks[position]
        log(tr('{arg0}：翻译第 {arg1}/{arg2} 段', arg0=source.name, arg1=position + 1, arg2=len(chunks)))
        attempt_drafts.clear()
        attempt_record.clear()
        try:
            first, record = translate_chunk(original, position + 1)
        except _RetryChunk:
            log(tr("已丢弃当前译文草稿，按用户选择重试此分段。"))
            continue
        except (BudgetExceeded, ResponseTooLong):
            if len(original) < 2:
                raise
            # Retry from the original, never truncate or slice a translated result.
            halves = budget_chunks(original, lambda value: len(value) <= len(original) // 2)
            chunks[position:position + 1] = halves
            log(tr("译文扩展或输出截断，已缩小原文分段并重新翻译核对。"))
            continue
        except ProcessingCancelled:
            raise
        except Exception as exc:
            if not attempt_drafts or (not decide and not options.force_auto):
                raise
            choice = "first" if options.force_auto else decide({"filename": source.name, "chunk": position + 1, "source": original,
                             **attempt_drafts, "problem": str(exc)})
            if choice == "retry":
                continue
            first = attempt_drafts.get(choice, attempt_drafts["first"])
            record = {**attempt_record, "chunk": position + 1, "verified": False,
                      "pendingReasons": list(dict.fromkeys(attempt_record.get("pendingReasons", []) + ["translation_check_failed"])),
                      "checkError": str(exc), "userDecision": choice, "candidates": dict(attempt_drafts)}
        if options.force_auto and "userDecision" in record:
            record["automaticDecision"] = "keep_pending"
            record.pop("userDecision", None)
        translated.append(first)
        records.append(dict(record))
        position += 1
    _cancel(stop)
    output = "\n\n".join(translated) + "\n"
    verified = bool(options.secondary_review or options.proofreading) and all(r["verified"] for r in records)
    report = {"status": "verified" if verified else "needs_review" if options.secondary_review or options.proofreading else "unverified",
              "verified": verified, "source": str(source), "path": str(destination),
              "sourceSHA256": hashlib.sha256(source_bytes).hexdigest(),
              "outputSHA256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
              "detectedLanguage": language["language"], "sourceLanguage": source_language,
              "targetLanguage": options.target, "translator": translator.model,
              "reviewer": reviewer.model if options.secondary_review else None,
              "proofreader": proofreader.model if options.proofreading else None,
              "arbiter": arbiter.model if model_arbitration else None,
              "arbitrationMode": options.arbitration,
              "allowArbiterRevision": options.allow_arbiter_revision is True,
              "forceAutomatic": options.force_auto is True,
              "arbiterRevisionAuthorized": revision_authorized,
              "pendingReasons": sorted({reason for record in records for reason in record["pendingReasons"]}),
              "inputPercent": percent, "tokenEstimate": "utf8_bytes_plus_framing",
              "modelLimits": {role: {**effective_limits(profile).__dict__, "input_budget": input_budget(profile, percent)}
                              for role, profile in active.items()}, "checks": records}
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects both the original and concurrently produced outputs.
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(output)
    destination.with_suffix(".translation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


FORMAT_PROMPT = ("你是 Markdown 文献排版编辑。只整理 source 的 Markdown 格式，便于人类阅读。"
    "合理使用现有标题的层级、段落与空行、列表、表格、引用和代码围栏；保留原有章节顺序与语言。"
    "不得翻译、摘要、润色、补写标题内容、修改措辞或擅自修复疑似 OCR 错字。"
    "完整保留全部正文、数字、引用、参考文献、代码、公式、图片与链接地址。"
    "已有代码块内容和数学公式必须原样保留。每个 source 只整理一次；不生成另一候选版本。"
    "只返回整理后的 Markdown，不添加说明，不把整篇文章套入代码围栏。")
FORMAT_VERIFY_PROMPT = ("独立校对 source 与 formatted。这是一次整理之后的二次核验，不是二次整理。"
    "检查全部内容、语种、顺序、数字、引文、参考文献、代码、公式、图片与链接是否保留，"
    "检查 Markdown 标题、段落、列表、表格和围栏是否清晰可读。疑似缺字或语句不通只指出，不擅自修正文稿。"
    "只能返回核验 JSON，绝不生成、改写或再次排版整理稿："
    '{"has_problem":true或false,"issues":["具体问题"],"summary":"结论"}。')


def _markdown_protected(text):
    """Ranges that must not be split across separate formatting requests."""
    ranges, fence, start, position = [], None, 0, 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if marker:
            run, tail = marker.groups()
            if fence is None:
                fence, start = run, position
            elif run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                ranges.append((start, position + len(line)))
                fence = None
        position += len(line)
    if fence:
        ranges.append((start, len(text)))
    ranges.extend((m.start(), m.end()) for m in re.finditer(r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]", text))
    # Contiguous Markdown table rows remain one unit, including the separator.
    ranges.extend((m.start(), m.end()) for m in re.finditer(r"(?m)^(?:[^\n]*\|[^\n]*\n){2,}", text))
    merged = []
    for begin, end in sorted(ranges):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((begin, end))
    return merged


def formatting_chunks(text, fits):
    units, position = [], 0
    for begin, end in _markdown_protected(text):
        units.extend(budget_chunks(text[position:begin], fits))
        block = text[begin:end]
        if not fits(block):
            raise ValueError(tr("完整代码块、公式或表格超出整理／核验模型预算，请提高上限或改用更大模型。"))
        units.append(block)
        position = end
    units.extend(budget_chunks(text[position:], fits))
    chunks = []
    for unit in units:
        if chunks and fits(chunks[-1] + unit):
            chunks[-1] += unit
        else:
            chunks.append(unit)
    return chunks


def formatting_content_issues(source, formatted):
    """Conservative checks supplement the LLM; formatting cannot approve content edits."""
    from collections import Counter
    def plain(text):
        text = re.sub(r"(?m)^ {0,3}(?:`{3,}|~{3,})[^\n]*$", "", text)
        return re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    left, right = plain(source), plain(formatted)
    issues = []
    if re.sub(r"[\W_]+", "", left) != re.sub(r"[\W_]+", "", right):
        issues.append(tr("整理稿的文字内容或顺序发生变化。"))
    if re.findall(r"\d+(?:[.,]\d+)*%?", left) != re.findall(r"\d+(?:[.,]\d+)*%?", right):
        issues.append(tr("整理稿中的数字发生变化。"))
    for pattern in (r"!?\[[^\]\n]*\]\(([^\n]*?)\)", r"https?://[^\s<>]+"):
        if Counter(re.findall(pattern, source)) != Counter(re.findall(pattern, formatted)):
            issues.append(tr("整理稿中的图片或链接地址发生变化。"))
            break
    # Match fence bodies independently of fence style/language labels.
    def code(text):
        result, fence, lines = [], None, []
        for line in text.splitlines(keepends=True):
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
            if fence is None and marker:
                fence, lines = marker.group(1), []
            elif fence and marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                result.append("".join(lines)); fence = None
            elif fence:
                lines.append(line)
        if fence:
            result.append("".join(lines))
        return result
    if Counter(code(source)) - Counter(code(formatted)):
        issues.append(tr("整理稿中的代码块内容发生变化。"))
    inline = r"(?<!`)(`{1,2})(?!`)([^\n]*?)\1(?!`)"
    if Counter(m.group(2) for m in re.finditer(inline, source)) - Counter(m.group(2) for m in re.finditer(inline, formatted)):
        issues.append(tr("整理稿中的行内代码发生变化。"))
    math = r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|(?<!\$)\$(?!\$)[^\n$]+\$(?!\$)"
    if Counter(re.findall(math, source)) != Counter(re.findall(math, formatted)):
        issues.append(tr("整理稿中的数学公式发生变化。"))
    return issues


def formatted_path(source, input_root, output_root=None, prefix=False):
    parent = source.parent if output_root is None else Path(output_root) / source.relative_to(input_root).parent
    name = f"FORMATTED_{source.stem}.md" if prefix else f"{source.stem}_FORMATTED.md"
    result = parent / name
    if result.resolve() == source.resolve():
        raise ValueError(tr("整理稿不能覆盖原文。"))
    return result


def find_formatting_files(root, recursive=True, output_root=None):
    root = Path(root).resolve()
    output = Path(output_root).resolve() if output_root else None
    paths = root.rglob("*") if recursive else root.iterdir()
    return sorted(path for path in paths if path.is_file() and path.suffix.lower() == ".md"
        and not any(p.is_symlink() for p in (path, *path.parents))
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and not path.stem.upper().startswith("FORMATTED_") and not path.stem.upper().endswith("_FORMATTED")
        and not path.with_suffix(".formatting.json").exists()
        and not (output and output != root and output in path.resolve().parents))


FORMAT_ARBITRATE_PROMPT = (
    '你是 Markdown 整理的最终核验裁决员。对照 source 和 formatted 检查内容、数字、引用、公式、表格及代码是否完整，'
    '判断已有 review 是否误报。只核验，不重新整理，不返回改写文本。仍有问题或无法确认时保持待处理。'
    '只返回 JSON：{"decision":"approve或needs_review","has_problem":true或false,"issues":["具体问题"]}。'
    '只有内容和结构均无问题才可 approve，且 has_problem=false、issues=[]。'
)


def format_markdown_document(source, destination, formatter, verifier, input_percent=50,
                             stop=lambda: False, log=lambda message: None, decide=None, force_auto=False, arbiter=None):
    """One formatting response and one independent, JSON-only review per source chunk."""
    if force_auto:
        if arbiter is None:
            raise ValueError(tr("请选择裁决模型。"))
        arbiter.validate()
        decide = None
    source, destination = Path(source), Path(destination)
    if destination.resolve() == source.resolve():
        raise ValueError(tr("整理稿不能覆盖原文。"))
    report_path = destination.with_suffix(".formatting.json")
    if destination.exists() or report_path.exists():
        return {"status": "existing", "verified": False, "path": str(destination)}
    for profile in (formatter, verifier):
        profile.validate()
    source_bytes = source.read_bytes()
    text = source_bytes.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError(tr("Markdown 文件为空，无法整理。"))
    def fits(original):
        _cancel(stop)
        try:
            check_request(formatter, FORMAT_PROMPT, {"source": original}, input_percent)
            check_request(verifier, FORMAT_VERIFY_PROMPT, {"source": original, "formatted": original * 2}, input_percent)
            if force_auto:
                check_request(arbiter, FORMAT_ARBITRATE_PROMPT,
                    {"source": original, "formatted": original * 2, "review": {"issues": [" " * 512]}}, input_percent)
            return True
        except BudgetExceeded:
            return False
    chunks = formatting_chunks(text, fits)
    output, records = [], []
    for index, original in enumerate(chunks, 1):
        prior = []
        while True:
            _cancel(stop)
            log(tr("{arg0}：整理第 {arg1}/{arg2} 段（仅整理一次）。", arg0=source.name, arg1=index, arg2=len(chunks)))
            candidate = chat(formatter, FORMAT_PROMPT, {"source": original}, stop, input_percent=input_percent)
            record = {"chunk": index, "attempt": len(prior) + 1, "verified": False,
                      "contentIssues": formatting_content_issues(original, candidate)}
            log(tr("{arg0}：第 {arg1} 段独立核验，不再次整理。", arg0=source.name, arg1=index))
            try:
                review = review_reply(chat(verifier, FORMAT_VERIFY_PROMPT, {"source": original, "formatted": candidate},
                                          stop, input_percent=input_percent))
                record["review"] = review
                if not isinstance(review.get("issues"), list) or any(not isinstance(item, str) for item in review["issues"]):
                    raise ValueError(tr("整理核验缺少有效的问题列表，不能视为通过。"))
                record["verified"] = not review["has_problem"] and not review["issues"] and not record["contentIssues"]
            except ProcessingCancelled:
                raise
            except Exception as exc:
                record["reviewError"] = str(exc)
            if force_auto and not record["verified"]:
                try:
                    verdict = review_reply(chat(arbiter, FORMAT_ARBITRATE_PROMPT,
                        {"source": original, "formatted": candidate, "review": dict(record)}, stop,
                        input_percent=input_percent))
                    record["arbitration"] = verdict
                    record["verified"] = (verdict.get("decision") == "approve" and not verdict["has_problem"]
                        and isinstance(verdict.get("issues"), list) and not verdict["issues"] and not record["contentIssues"])
                except ProcessingCancelled:
                    raise
                except Exception as exc:
                    record["arbitrationError"] = str(exc)
            if not record["verified"] and decide:
                choice = decide({"filename": source.name, "chunk": index, "source": original,
                                 "first": candidate, "problem": dict(record)})
                if choice == "retry":
                    prior.append(record)
                    log(tr("已丢弃当前整理稿，按用户选择重试此分段。"))
                    continue
                record["userDecision"] = choice
            record["priorAttempts"] = prior
            break
        output.append(candidate)
        records.append(record)
    _cancel(stop)
    result_text = "\n\n".join(output) + "\n"
    issues = formatting_content_issues(text, result_text)
    verified = all(r["verified"] for r in records) and not issues
    try:
        role, upstream, digest = document_upload_evidence(source)
        upstream_verified = upstream == "ready" and digest == hashlib.sha256(source_bytes).hexdigest()
    except (OSError, ValueError, UnicodeError):
        role, upstream_verified = "original", False
    report = {"status": "verified" if verified else "needs_review", "verified": verified,
        "source": str(source), "path": str(destination), "sourceSHA256": hashlib.sha256(source_bytes).hexdigest(),
        "outputSHA256": hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
        "formatter": formatter.model, "verifier": verifier.model, "inputPercent": input_percent,
        "formattingPasses": max(r["attempt"] for r in records), "userRetries": sum(len(r["priorAttempts"]) for r in records),
        "verificationOnly": True, "forceAutomatic": bool(force_auto),
        "arbiter": arbiter.model if force_auto else None, "documentRole": role, "upstreamVerified": upstream_verified,
        "contentIssues": issues, "checks": records,
        "pendingReasons": [] if verified else ["formatting_verification_failed"],
        "modelLimits": {name: {**effective_limits(profile).__dict__, "input_budget": input_budget(profile, input_percent)}
                        for name, profile in (("formatter", formatter), ("verifier", verifier))}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserve both names exclusively; never replace a previous result or report.
    with report_path.open("x", encoding="utf-8", newline="\n") as report_file:
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as document:
                document.write(result_text)
            json.dump(report, report_file, ensure_ascii=False, indent=2)
        except BaseException:
            report_path.unlink(missing_ok=True)
            raise
    return report


def ocr_verified(raw_data: dict) -> bool:
    """Require positive LLM evidence for every OCR part, and reject warnings anywhere."""
    if not isinstance(raw_data, dict):
        return False
    reviews = []
    def walk(value):
        if isinstance(value, dict):
            if value.get("qualityWarning"):
                reviews.append(False)
            if "llmReviewError" in value or (isinstance(value.get("wordCountCheck"), dict)
                    and value["wordCountCheck"].get("passed") is not True):
                reviews.append(False)
            if "llmReview" in value:
                review = value["llmReview"]
                reviews.append(isinstance(review, dict) and review.get("hasProblem") is False)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
    walk(raw_data)
    if raw_data.get("parts"):
        return all(ocr_verified(part) for part in raw_data["parts"]) and bool(reviews) and all(reviews)
    return bool(reviews) and all(reviews)


@dataclass(frozen=True)
class GitHubOptions:
    repository: str
    token: str = field(repr=False)
    branch: str = "main"
    folder: str = ""

    def validate(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) or any(part in {".", ".."} for part in self.repository.split("/")):
            raise ValueError(tr('GitHub 仓库请填写 owner/repository。'))
        if not self.token.strip() or not self.branch.strip():
            raise ValueError(tr('请填写 GitHub Token 和目标分支。'))
        if "\\" in self.folder or self.folder.startswith("/") or ".." in PurePosixPath(self.folder).parts:
            raise ValueError(tr('GitHub 目录必须是仓库内的相对路径。'))


def github_repository_name(value: str) -> str:
    """Accept a repository name or a copied GitHub page URL, never a custom API host."""
    value = value.strip()
    if value.startswith("github.com/"):
        value = "https://" + value
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.username:
            raise ValueError(tr("请粘贴 github.com 的仓库链接，或填写 owner/repository。"))
        value = "/".join(parsed.path.strip("/").split("/")[:2])
    value = value.rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(tr("请粘贴 github.com 的仓库链接，或填写 owner/repository。"))
    return value


def github_folder_name(value: str) -> str:
    value = value.strip()
    if value == "/":
        return ""
    if "\\" in value or value.startswith("/") or "://" in value or ".." in PurePosixPath(value).parts:
        raise ValueError(tr('GitHub 目录必须是仓库内的相对路径。'))
    return str(PurePosixPath(value)) if value and value != "." else ""


@dataclass
class GitHubSetupClient:
    """Read-only setup checks. This client never sends a write request."""
    token: str = field(repr=False)
    stop: Callable[[], bool] = field(default=lambda: False, repr=False)

    def get(self, path, params=None, missing_ok=False):
        _cancel(self.stop)
        if not self.token.strip():
            raise ValueError(tr("请先粘贴 GitHub 访问凭据（Token）。"))
        if requests is None:
            raise RuntimeError(tr('缺少 requests。'))
        try:
            response = cancellable_call(lambda: requests.get("https://api.github.com" + path,
                headers={"Authorization": f"Bearer {self.token.strip()}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"},
                params=params, timeout=(10, 30), allow_redirects=False), self.stop, timeout=50, cancelled=ProcessingCancelled)
        except requests.RequestException:
            raise RuntimeError(tr("无法连接 GitHub，请检查网络或代理后重试。")) from None
        _cancel(self.stop)
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code == 401:
            raise ValueError(tr("访问凭据无效或已过期，请重新生成并粘贴 Token。"))
        if response.status_code in {403, 429}:
            raise RuntimeError(tr("GitHub 拒绝访问或请求次数已达上限，请检查凭据权限，稍后重试。"))
        if response.status_code == 404:
            raise ValueError(tr("找不到仓库或分支，请检查选择，并确认 Token 已授权访问该仓库。"))
        if response.status_code != 200:
            raise RuntimeError(tr("GitHub 连接检查失败（HTTP {arg0}），请稍后重试。", arg0=response.status_code))
        try:
            return response.json()
        except ValueError:
            raise RuntimeError(tr("GitHub 返回的数据无法读取，请稍后重试。")) from None

    def pages(self, path, **params):
        result = []
        page = 1
        seen = set()
        while True:
            _cancel(self.stop)
            values = self.get(path, {**params, "per_page": 100, "page": page})
            if not isinstance(values, list):
                raise RuntimeError(tr("GitHub 返回的数据无法读取，请稍后重试。"))
            identity = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if identity in seen or page > 1000:
                raise RuntimeError(tr("GitHub 分页结果重复或过多，已停止读取，请缩小范围后重试。"))
            seen.add(identity)
            result.extend(value for value in values if isinstance(value, dict))
            if len(values) < 100:
                return result
            page += 1

    def connect(self):
        user = self.get("/user")
        if not isinstance(user, dict) or not isinstance(user.get("login"), str):
            raise RuntimeError(tr("GitHub 返回的数据无法读取，请稍后重试。"))
        repos = self.pages("/user/repos", sort="updated", affiliation="owner,collaborator,organization_member")
        names = [repo["full_name"] for repo in repos if isinstance(repo.get("full_name"), str)
                 and not repo.get("archived") and not repo.get("disabled")
                 and (repo.get("permissions") or {}).get("push") is not False]
        return {"login": user["login"], "repositories": names}

    def repository(self, repository):
        repository = github_repository_name(repository)
        info = self.get(f"/repos/{repository}")
        if not isinstance(info, dict):
            raise RuntimeError(tr("GitHub 返回的数据无法读取，请稍后重试。"))
        if info.get("archived") or info.get("disabled"):
            raise ValueError(tr("该仓库已归档或停用，请选择可写入的仓库。"))
        if (info.get("permissions") or {}).get("push") is False:
            raise ValueError(tr("当前账号没有该仓库的写入权限，请换一个仓库或联系仓库所有者。"))
        return info

    def prepare_repository(self, repository):
        repository = github_repository_name(repository)
        info = self.repository(repository)
        branches = self.pages(f"/repos/{repository}/branches")
        names = [value["name"] for value in branches if isinstance(value.get("name"), str)]
        if not names:
            raise ValueError(tr("仓库还没有分支，请先在 GitHub 添加 README 文件，再返回重试。"))
        return {"repository": repository, "branches": names, "default_branch": info.get("default_branch", names[0])}

    def folders(self, repository, branch, folder=""):
        repository, folder = github_repository_name(repository), github_folder_name(folder)
        values = self.get(f"/repos/{repository}/contents/{quote(folder, safe='/')}", {"ref": branch})
        if not isinstance(values, list):
            raise ValueError(tr("此路径是文件，请选择文件夹。"))
        return [value["path"] for value in values if isinstance(value, dict) and value.get("type") == "dir"
                and isinstance(value.get("path"), str)]

    def check_destination(self, options):
        options.validate()
        self.repository(options.repository)
        self.get(f"/repos/{options.repository}/branches/{quote(options.branch, safe='')}")
        folder = github_folder_name(options.folder)
        while folder:
            value = self.get(f"/repos/{options.repository}/contents/{quote(folder, safe='/')}",
                             {"ref": options.branch}, missing_ok=True)
            if value is not None:
                if not isinstance(value, list):
                    raise ValueError(tr("目标路径中已有同名文件，请改用其他文件夹名称。"))
                break
            parent = str(PurePosixPath(folder).parent)
            folder = "" if parent == "." else parent
        return True

    def remote_paths(self, options):
        """Read the complete tree; a truncated recursive response is never treated as complete."""
        options.validate()
        branch = self.get(f"/repos/{options.repository}/branches/{quote(options.branch, safe='')}")
        tree_sha = branch["commit"]["commit"]["tree"]["sha"]
        route = f"/repos/{options.repository}/git/trees/"
        tree = self.get(route + quote(tree_sha, safe=""), {"recursive": "1"})
        paths = set()
        if not tree.get("truncated"):
            return {item["path"] for item in tree["tree"]}
        pending = [("", tree_sha)]
        while pending:
            prefix, sha = pending.pop()
            value = self.get(route + quote(sha, safe=""))
            if value.get("truncated"):
                raise RuntimeError(tr("远端目录过大，无法完整比较；本次未上传，请缩小目标目录后重试。"))
            for item in value["tree"]:
                name = prefix + item["path"]
                paths.add(name)
                if item.get("type") == "tree":
                    pending.append((name + "/", item["sha"]))
        return paths


UPLOAD_KINDS = ("仅上传原文", "仅上传翻译稿", "同时上传")


def upload_kind_allows(selection, role):
    return selection == "同时上传" or selection == {"original": "仅上传原文", "translation": "仅上传翻译稿"}.get(role)


@dataclass(frozen=True)
class UploadCandidate:
    path: Path
    relative: str
    role: str
    status: str
    sha256: str


def review_text_sha256(text):
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").strip().encode("utf-8")).hexdigest()


def document_upload_evidence(path):
    """Bind positive local review evidence to the current bytes/text, including old reports."""
    format_report = path.with_suffix(".formatting.json")
    report_path = format_report if format_report.exists() else path.with_suffix(".translation.json")
    translated = path.with_suffix(".translation.json").exists() or path.stem.upper().startswith("TRANSLATED_") or path.stem.upper().endswith("_TRANSLATED")
    if format_report.exists():
        try:
            value = json.loads(format_report.read_text(encoding="utf-8-sig"))
            if isinstance(value, dict):
                translated = value.get("documentRole") == "translation"
        except (OSError, ValueError, UnicodeError):
            pass
    if path.stat().st_size > 20 * 1024 * 1024:
        return ("translation" if translated else "original"), "oversize", ""
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    def load(report):
        value = json.loads(report.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("invalid report")
        return value
    if report_path.exists():
        report = load(report_path)
        translated = report.get("documentRole") == "translation" if format_report.exists() else True
        ok = (report.get("verified") is True and report.get("status") == "verified"
              and report.get("upstreamVerified", not format_report.exists()) is True and not report.get("pendingReasons"))
        matches = report.get("outputSHA256") == digest
    else:
        review_path = path.with_suffix(".llm-review.json")
        if not review_path.exists():
            return ("translation" if translated else "original"), "unverified", digest
        review = load(review_path)
        ok = review.get("hasProblem") is False
        # read_text normalizes CRLF just as the manual OCR review does.
        text_digest = review_text_sha256(path.read_text(encoding="utf-8"))
        matches = review.get("textSHA256") == text_digest
        if not translated:
            for suffix in (".raw.json", ".json"):
                raw_path = path.with_suffix(suffix)
                if raw_path.exists():
                    raw = load(raw_path)
                    def warning(value):
                        return (isinstance(value, dict) and (bool(value.get("qualityWarning"))
                                or any(warning(v) for v in value.values()))) or (isinstance(value, list) and any(warning(v) for v in value))
                    ok = ok and not warning(raw)
    status = "ready" if ok and matches else "changed" if ok and not matches else "unverified"
    if len(content) > 20 * 1024 * 1024:
        status = "oversize"
    return ("translation" if translated else "original"), status, digest


def scan_missing_documents(root, selection, options, recursive=True, stop=lambda: False, client=None):
    if not str(root).strip():
        raise ValueError(tr("请选择有效的文档文件夹和上传类型。"))
    root = Path(root).expanduser().resolve()
    if not root.is_dir() or selection not in UPLOAD_KINDS:
        raise ValueError(tr("请选择有效的文档文件夹和上传类型。"))
    options.validate()
    client = client or GitHubSetupClient(options.token, stop)
    remote = client.remote_paths(options)
    candidates = []
    for path in sorted(root.rglob("*") if recursive else root.iterdir()):
        _cancel(stop)
        relative = path.relative_to(root)
        if (path.suffix.lower() != ".md" or not path.is_file() or any(p.startswith(".") for p in relative.parts)
                or any(p.is_symlink() for p in (path, *path.parents))):
            continue
        role = "translation" if path.with_suffix(".translation.json").exists() or path.stem.upper().startswith("TRANSLATED_") or path.stem.upper().endswith("_TRANSLATED") else "original"
        if path.with_suffix(".formatting.json").exists():
            try:
                evidence = json.loads(path.with_suffix(".formatting.json").read_text(encoding="utf-8-sig"))
                if isinstance(evidence, dict) and evidence.get("documentRole") in {"original", "translation"}:
                    role = evidence["documentRole"]
            except (OSError, ValueError, UnicodeError):
                pass
        if not upload_kind_allows(selection, role):
            continue
        name = str(PurePosixPath(options.folder) / relative.as_posix())
        if name in remote:
            status, digest = "existing", ""
        else:
            try:
                role, status, digest = document_upload_evidence(path)
            except (OSError, ValueError, UnicodeError):
                status, digest = "unverified", ""
        candidates.append(UploadCandidate(path, relative.as_posix(), role, status, digest))
    return candidates


def upload_verified_file(path: Path, relative_name: str, verified: bool, options: GitHubOptions,
                         expected_sha256: str, stop=lambda: False) -> str:
    if verified is not True:
        raise ValueError(tr('文件尚未核验通过，禁止自动上传。'))
    options.validate()
    _cancel(stop)
    if requests is None:
        raise RuntimeError(tr('缺少 requests。'))
    if relative_name.startswith("/") or "\\" in relative_name or ".." in PurePosixPath(relative_name).parts:
        raise ValueError(tr('上传路径必须是相对路径。'))
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError(tr('核验后文件发生变化，请重新核验再上传。'))
    if len(content) > 20 * 1024 * 1024:
        raise ValueError(tr('自动上传仅支持 20MB 以内的文件。'))
    remote = str(PurePosixPath(options.folder) / relative_name)
    url = f"https://api.github.com/repos/{options.repository}/contents/{quote(remote, safe='/')}"
    headers = {"Authorization": f"Bearer {options.token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    response = requests.get(url, headers=headers, params={"ref": options.branch}, timeout=(15, 60), allow_redirects=False)
    if response.status_code == 200:
        raise FileExistsError(tr('GitHub 已存在 {arg0}；为避免覆盖，未上传。', arg0=remote))
    if response.status_code != 404:
        raise RuntimeError(tr('读取 GitHub 仓库失败：HTTP {arg0}。', arg0=response.status_code))
    _cancel(stop)
    response = requests.put(url, headers=headers, json={
        "message": f"Add reviewed literature: {remote}", "branch": options.branch,
        "content": base64.b64encode(content).decode("ascii"),
    }, timeout=(15, 60), allow_redirects=False)
    if response.status_code != 201:
        raise RuntimeError(tr('GitHub 上传失败：HTTP {arg0}。请检查分支和 Contents 写入权限。', arg0=response.status_code))
    return remote
