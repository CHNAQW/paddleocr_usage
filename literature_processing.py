"""Translation and reviewed-document publishing, independent of the GUI."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import quote, urlparse

from ui_translations import tr
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
    response = requests.post(
        profile.base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {profile.api_key.strip()}", "Content-Type": "application/json"},
        json=body, timeout=(15, 300),
    )
    _cancel(stop)
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
        if path.stem.upper().startswith("TRANSLATED_") or path.stem.upper().endswith("_TRANSLATED"):
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


def translate_document(source: Path, destination: Path, options: TranslationOptions,
                       translator: ModelProfile, reviewer: ModelProfile | None = None,
                       proofreader: ModelProfile | None = None, arbiter: ModelProfile | None = None,
                       decide=None, stop=lambda: False, log=lambda message: None) -> dict:
    """Return an auditable result. Unresolved documents are saved but never approved."""
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
                    check_request(arbiter, ARBITRATE_PROMPT,
                                  {**candidates, "comparison": report_reserve}, percent)
            if options.proofreading:
                check_request(proofreader, PROOFREAD_PROMPT, {**data, "translation": original * 2}, percent)
                if model_arbitration:
                    check_request(arbiter, PROOF_ARBITRATE_PROMPT,
                                  {**data, "translation": original * 2, "proofreading": report_reserve}, percent)
            return True
        except BudgetExceeded:
            return False

    chunks = budget_chunks(text, fits)
    def translate_chunk(original, index):
        data = data_for(original)
        first = ask(translator, TRANSLATE_PROMPT, data)
        record = {"chunk": index, "verified": True, "pendingReasons": []}
        if options.secondary_review:
            log(tr('{arg0}：第 {arg1} 段二次翻译核对', arg0=source.name, arg1=index))
            second = ask(reviewer, TRANSLATE_PROMPT, data)
            comparison = review_reply(ask(reviewer, COMPARE_PROMPT,
                {**data, "first": first, "second": second}))
            record["comparison"] = comparison
            if comparison["has_problem"]:
                if options.arbitration == "大模型裁决":
                    log(tr("{arg0}：第 {arg1} 段开始翻译分歧裁决，模型 {arg2}。",
                           arg0=source.name, arg1=index, arg2=arbiter.model))
                    verdict = review_reply(ask(arbiter, ARBITRATE_PROMPT,
                        {**data, "first": first, "second": second, "comparison": comparison}))
                    raw_choice = verdict.get("choice")
                    raw_choice = raw_choice.strip().lower() if isinstance(raw_choice, str) else "unresolved"
                    choice = raw_choice if raw_choice in {"first", "second"} and not verdict["has_problem"] else "unresolved"
                    record["arbitration"] = verdict
                    record["arbitrationChoice"] = choice
                    log(tr("{arg0}：第 {arg1} 段翻译裁决结果：{arg2}；理由：{arg3}",
                           arg0=source.name, arg1=index,
                           arg2=tr({"first": "接受首次译文", "second": "接受二次译文", "unresolved": "未能明确批准译文"}[choice]),
                           arg3=verdict.get("reason") or tr("模型未提供理由")))
                else:
                    log(tr("{arg0}：第 {arg1} 段翻译有分歧，等待用户裁决。", arg0=source.name, arg1=index))
                    choice = decide({"filename": source.name, "chunk": index, "source": original,
                                     "first": first, "second": second, "comparison": comparison}) if decide else "unresolved"
                    record["arbitration"] = {"choice": choice, "by": "user"}
                record["candidates"] = {"first": first, "second": second}
                if choice == "second":
                    first = second
                elif choice != "first":
                    record["verified"] = False
                    record["pendingReasons"].append("translation_dispute_unresolved")
        if options.proofreading:
            log(tr('{arg0}：第 {arg1} 段文本校对', arg0=source.name, arg1=index))
            proof = review_reply(ask(proofreader, PROOFREAD_PROMPT, {**data, "translation": first}))
            record["proofreading"] = proof
            proof_passed = not proof["has_problem"]
            if not proof_passed and model_arbitration:
                log(tr("{arg0}：第 {arg1} 段开始校对疑点裁决，模型 {arg2}。",
                       arg0=source.name, arg1=index, arg2=arbiter.model))
                verdict = review_reply(ask(arbiter, PROOF_ARBITRATE_PROMPT,
                    {**data, "translation": first, "proofreading": proof}))
                proof_passed = verdict.get("decision") == "approve" and not verdict["has_problem"]
                record["proofreadingArbitration"] = verdict
                log(tr("{arg0}：第 {arg1} 段校对裁决结果：{arg2}；理由：{arg3}",
                       arg0=source.name, arg1=index,
                       arg2=tr("校对疑点已排除") if proof_passed else tr("校对疑点尚未解决"),
                       arg3=verdict.get("reason") or tr("模型未提供理由")))
            if not proof_passed:
                record["pendingReasons"].append("proofreading_problem")
                log(tr("{arg0}：第 {arg1} 段校对疑点尚未解决，本段保持待处理。", arg0=source.name, arg1=index))
            record["verified"] = record["verified"] and proof_passed
        return first, record

    position = 0
    while position < len(chunks):
        _cancel(stop)
        original = chunks[position]
        log(tr('{arg0}：翻译第 {arg1}/{arg2} 段', arg0=source.name, arg1=position + 1, arg2=len(chunks)))
        try:
            first, record = translate_chunk(original, position + 1)
        except (BudgetExceeded, ResponseTooLong):
            if len(original) < 2:
                raise
            # Retry from the original, never truncate or slice a translated result.
            halves = budget_chunks(original, lambda value: len(value) <= len(original) // 2)
            chunks[position:position + 1] = halves
            log(tr("译文扩展或输出截断，已缩小原文分段并重新翻译核对。"))
            continue
        translated.append(first)
        records.append(record)
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
            response = requests.get("https://api.github.com" + path,
                headers={"Authorization": f"Bearer {self.token.strip()}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"},
                params=params, timeout=(10, 30), allow_redirects=False)
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
        while True:
            values = self.get(path, {**params, "per_page": 100, "page": page})
            if not isinstance(values, list):
                raise RuntimeError(tr("GitHub 返回的数据无法读取，请稍后重试。"))
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
    response = requests.get(url, headers=headers, params={"ref": options.branch}, timeout=(15, 60))
    if response.status_code == 200:
        raise FileExistsError(tr('GitHub 已存在 {arg0}；为避免覆盖，未上传。', arg0=remote))
    if response.status_code != 404:
        raise RuntimeError(tr('读取 GitHub 仓库失败：HTTP {arg0}。', arg0=response.status_code))
    _cancel(stop)
    response = requests.put(url, headers=headers, json={
        "message": f"Add reviewed literature: {remote}", "branch": options.branch,
        "content": base64.b64encode(content).decode("ascii"),
    }, timeout=(15, 60))
    if response.status_code != 201:
        raise RuntimeError(tr('GitHub 上传失败：HTTP {arg0}。请检查分支和 Contents 写入权限。', arg0=response.status_code))
    return remote
