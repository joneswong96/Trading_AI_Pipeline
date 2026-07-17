"""Manual shadow fallback and offline inspection CLI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from contracts import canonical_json

from .audit import ShadowAuditStore
from .clients import OpenClawCliClient, RecordedModelClient
from .configuration import load_and_render_template
from .models import Artifact, DispatchEnvelope, ModelIdentity, RuntimePolicy
from .service import ReviewService
from .telegram_policy import TelegramPolicy


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed.astimezone(timezone.utc)


def _load_dispatch(path: Path, artifact_root: Path | None = None) -> DispatchEnvelope:
    document = json.loads(path.read_text(encoding="utf-8"))
    if artifact_root is not None:
        root = artifact_root.resolve()
    else:
        root = Path(document["artifact_root"])
    if artifact_root is None and not root.is_absolute():
        root = (path.parent / root).resolve()
    return DispatchEnvelope(
        dispatch_id=document["dispatch_id"],
        request=document["request"],
        bundle_hash=document["bundle_hash"],
        artifact_manifest=tuple(Artifact(**item) for item in document["artifact_manifest"]["artifacts"]),
        artifact_manifest_hash=document["artifact_manifest_hash"],
        artifact_root=root,
        attempt_metadata=document.get("attempt_metadata", {}),
    )


def _result(service: ReviewService, dispatch: DispatchEnvelope, retry_of: str | None) -> int:
    result = service.review(dispatch, retry_of=retry_of)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.status == "VERDICT" else 2


def _review_recorded(args) -> int:
    now = _utc(args.now)
    client = RecordedModelClient(
        raw_response=Path(args.response).read_text(encoding="utf-8"),
        identity=ModelIdentity(args.provider, args.model, args.auth_mode),
    )
    service = ReviewService(
        audit_store=ShadowAuditStore(Path(args.audit_root)),
        client=client,
        policy=RuntimePolicy(openclaw_version="MANUAL_FALLBACK", auth_mode=args.auth_mode),
        clock=lambda: now,
    )
    return _result(service, _load_dispatch(Path(args.dispatch), Path(args.artifact_root) if args.artifact_root else None), args.retry_of)


def _review_openclaw(args) -> int:
    now_override = _utc(args.now) if args.now else None
    client = OpenClawCliClient(
        executable=args.executable,
        model=args.model,
        staging_root=Path(args.staging_root),
        required_version=args.required_version,
    )
    version = client.version()
    service = ReviewService(
        audit_store=ShadowAuditStore(Path(args.audit_root)),
        client=client,
        policy=RuntimePolicy(openclaw_version=version),
        clock=(lambda: now_override) if now_override else None,
    )
    return _result(service, _load_dispatch(Path(args.dispatch), Path(args.artifact_root) if args.artifact_root else None), args.retry_of)


def _validate_config(args) -> int:
    rendered = load_and_render_template(Path(args.template), os.environ)
    output = {"ok": True, "agent": "project-a-reviewer", "security_posture": "PASS"}
    if args.output:
        Path(args.output).write_text(canonical_json(rendered) + "\n", encoding="utf-8")
        output["rendered_path"] = str(Path(args.output))
    print(json.dumps(output, indent=2))
    return 0


def _verify_audit(args) -> int:
    ok = ShadowAuditStore(Path(args.audit_root)).verify_chain(args.request_id)
    print(json.dumps({"request_id": args.request_id, "chain_valid": ok}))
    return 0 if ok else 2


def _telegram_check(args) -> int:
    update = json.loads(Path(args.update).read_text(encoding="utf-8"))
    command = TelegramPolicy.from_environment(os.environ).authorize(update)
    print(json.dumps({"authorized": True, "command": command.name, "request_id": command.request_id}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    recorded = sub.add_parser("review-recorded", help="manual/model response through identical gates")
    recorded.add_argument("--dispatch", required=True)
    recorded.add_argument("--response", required=True)
    recorded.add_argument("--artifact-root")
    recorded.add_argument("--audit-root", required=True)
    recorded.add_argument("--provider", required=True)
    recorded.add_argument("--model", required=True)
    recorded.add_argument("--auth-mode", default="manual-subscription")
    recorded.add_argument("--now")
    recorded.add_argument("--retry-of")
    recorded.set_defaults(func=_review_recorded)

    live = sub.add_parser("review-openclaw", help="guarded dedicated-agent invocation")
    live.add_argument("--dispatch", required=True)
    live.add_argument("--artifact-root")
    live.add_argument("--audit-root", required=True)
    live.add_argument("--staging-root", required=True)
    live.add_argument("--model", required=True)
    live.add_argument("--executable", default="openclaw")
    live.add_argument("--required-version", required=True)
    live.add_argument("--now")
    live.add_argument("--retry-of")
    live.set_defaults(func=_review_openclaw)

    config = sub.add_parser("validate-config")
    config.add_argument(
        "--template",
        default=str(Path(__file__).resolve().parents[1] / "config_templates" / "project_a_reviewer" / "openclaw.json"),
    )
    config.add_argument("--output", help="optional protected runtime output; never commit it")
    config.set_defaults(func=_validate_config)

    audit = sub.add_parser("verify-audit")
    audit.add_argument("--audit-root", required=True)
    audit.add_argument("--request-id", required=True)
    audit.set_defaults(func=_verify_audit)

    telegram = sub.add_parser("telegram-check")
    telegram.add_argument("--update", required=True)
    telegram.set_defaults(func=_telegram_check)
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
