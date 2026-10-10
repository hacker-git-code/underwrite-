"""underwrite: command-line entry point."""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path
from typing import Optional

import typer

from . import obs
from .config import settings
from .obs import console

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Underwrite: a due-diligence agent you can leave running overnight.")


MODE_HELP = "agent (analyst + skeptic agents, default) or pipeline (the original fixed flow)"


def _start(version: str | None, chaos: float | None, command: str, mode: str | None = None) -> str:
    version = version or settings.prompts_version
    settings.prompts_version = version
    if chaos is not None:
        settings.chaos = chaos
    if mode:
        if mode not in ("agent", "pipeline"):
            raise typer.BadParameter("mode must be agent or pipeline")
        settings.mode = mode
    tags = [f"prompts:{version}", f"cmd:{command}", f"mode:{settings.mode}"] + (["chaos"] if settings.chaos else [])
    obs.setup(tags=tags)
    return version


def _parse_line(line: str) -> tuple[str, str | None] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    name, _, domain = line.partition(",")
    return name.strip(), (domain.strip() or None)


@app.command()
def run(
    company: str = typer.Argument(..., help="Company name, e.g. 'Linear'"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Website domain, e.g. linear.app"),
    prompts: Optional[str] = typer.Option(None, "--prompts", "-p", help="Prompt version (default: UW_PROMPTS or v1)"),
    chaos: Optional[float] = typer.Option(None, help="Inject faults at this rate (0-1) to demo recovery"),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML memo when done"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help=MODE_HELP),
):
    """Research one company and write a cited memo."""
    from .pipeline import run_batch

    version = _start(prompts, chaos, "run", mode)
    run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}"
    [state] = run_batch([(company, domain)], run_id, version)
    _finish([state], run_id, open_report)


@app.command()
def batch(
    file: Path = typer.Argument(..., exists=True, help="Text file: one 'Company, domain' per line"),
    prompts: Optional[str] = typer.Option(None, "--prompts", "-p"),
    chaos: Optional[float] = typer.Option(None),
    new_only: bool = typer.Option(False, "--new-only", help="Skip companies already published on the site"),
    limit: Optional[int] = typer.Option(None, help="Research at most N companies this run"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help=MODE_HELP),
):
    """Research a list of companies unattended (the overnight mode)."""
    from .pipeline import run_batch, slug
    from .site import published_slugs

    version = _start(prompts, chaos, "batch", mode)
    companies = [p for p in map(_parse_line, file.read_text(encoding="utf-8").splitlines()) if p]
    if new_only:
        done = published_slugs()
        companies = [c for c in companies if slug(c[0]) not in done]
    companies = companies[:limit] if limit else companies
    if not companies:
        console.print("nothing new to research")
        return
    run_id = f"batch-{time.strftime('%Y%m%d-%H%M%S')}"
    console.print(f"[bold]batch {run_id}[/bold]: {len(companies)} companies. Ctrl-C is safe: `underwrite resume {run_id}`")
    states = run_batch(companies, run_id, version)
    _finish(states, run_id, False)


@app.command()
def resume(run_id: str = typer.Argument(..., help="Run id under runs/")):
    """Continue an interrupted run from the last saved phase of each company."""
    from .pipeline import resume as do_resume

    _start(None, None, "resume")
    states = do_resume(run_id)
    _finish(states, run_id, False)


def _finish(states, run_id: str, open_report: bool) -> None:
    import neatlogs

    from .pipeline import company_dir

    neatlogs.flush()
    ok = [s for s in states if s.phase == "done"]
    console.rule(f"{len(ok)}/{len(states)} memos complete · runs/{run_id}")
    for s in states:
        report = company_dir(run_id, s.company) / "memo.html"
        status = "[green]done[/green]" if s.phase == "done" else f"[red]stopped at {s.phase}[/red]: {s.error}"
        console.print(f"  {s.company}: {status}  {report if report.exists() else ''}")
        if s.trace_ids:
            console.print(f"    neatlogs trace: {', '.join(s.trace_ids)}")
        if open_report and report.exists():
            webbrowser.open(report.resolve().as_uri())
    if len(ok) < len(states):
        console.print(f"Resume with: [bold]underwrite resume {run_id}[/bold]")


@app.command("eval")
def eval_cmd(
    prompts: Optional[str] = typer.Option(None, "--prompts", "-p"),
    split: str = typer.Option("all", help="all | train | test"),
    limit: Optional[int] = typer.Option(None, help="Only the first N companies"),
    chaos: Optional[float] = typer.Option(None),
    resume_id: Optional[str] = typer.Option(None, "--resume", help="Finish an interrupted eval run (its run id)"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help=MODE_HELP),
):
    """Score a prompt version against the ground-truth dataset."""
    from .evals import run_eval

    if resume_id and not prompts:  # an eval run id looks like eval-<version>-<split>-<timestamp>
        prompts = resume_id.split("-")[1]
    version = _start(prompts, chaos, "eval", mode)
    path = run_eval(version, split, limit, resume_id=resume_id, mode=mode)
    console.print(f"eval written to {path}")


@app.command()
def coach(
    base: str = typer.Option("v1", help="Prompt version to improve"),
    no_eval: bool = typer.Option(False, "--no-eval", help="Only propose the new version; don't evaluate it"),
    split: str = typer.Option("all", help="Dataset split to run evals on"),
):
    """Improve the agent from its neatlogs traces and eval failures, then keep the change only if it scores better."""
    from .coach import coach as do_coach

    _start(base, None, "coach")
    report = do_coach(base, run_eval=not no_eval, split=split)
    console.print_json(data={k: v for k, v in report.items() if k in ("base", "new", "decision", "diagnosis")})


@app.command("watch")
def watch_cmd(limit: Optional[int] = typer.Option(None, help="Check at most N companies")):
    """Re-check researched companies; when something changed, the agent re-investigates just that and re-writes the memo."""
    from .watch import watch

    _start(None, None, "watch", "agent")
    states = watch(limit)
    if states:
        _finish(states, states[0].run_id, False)
    else:
        console.print("no material changes found")


@app.command("rescore")
def rescore_cmd(run_id: str = typer.Argument(..., help="Eval run id, e.g. eval-v1-all-20261010-140921")):
    """Re-grade a finished eval against the current ground truth, using the memos it already wrote."""
    from .evals import print_eval, rescore

    print_eval(rescore(settings.runs_dir / run_id / "eval.json"))


@app.command()
def compare(
    a: str = typer.Argument(..., help="[mode:]version (e.g. pipeline:v1, agent:v2) or a path to eval.json"),
    b: str = typer.Argument(..., help="[mode:]version (e.g. pipeline:v1, agent:v2) or a path to eval.json"),
    split: str = typer.Option("test"),
):
    """Before/after table between two evals."""
    from .evals import compare as do_compare
    from .evals import latest_eval

    def resolve(x: str) -> Path | None:
        p = Path(x)
        if p.exists():
            return p
        mode, _, version = x.rpartition(":")
        return latest_eval(version, mode or None)

    pa, pb = resolve(a), resolve(b)
    if not pa or not pb:
        raise typer.BadParameter("no eval found; run `underwrite eval --prompts <version>` first")
    do_compare(pa, pb, split)


@app.command()
def render(
    run_id: str = typer.Argument(..., help="Run id under runs/"),
    open_report: bool = typer.Option(False, "--open", help="Open the memo when done"),
):
    """Re-draw the memo dossier (HTML + PDF) for every finished company in a run, without re-running the agent."""
    from .models import CompanyState
    from .report import write_report

    for path in sorted((settings.runs_dir / run_id).glob("*/state.json")):
        state = CompanyState.model_validate_json(path.read_text(encoding="utf-8"))
        if state.phase != "done":
            continue
        out = write_report(state, path.parent)
        pdf = out.with_name("memo.pdf")
        console.print(f"{state.company}: {out}  {'+ memo.pdf' if pdf.exists() else '(no PDF: Edge/Chrome not found)'}")
        if open_report:
            webbrowser.open(out.resolve().as_uri())


@app.command()
def site(open_site: bool = typer.Option(False, "--open", help="Open the site when done")):
    """Build the static website in docs/ (memo gallery + scoreboard) for GitHub Pages."""
    from .site import build

    index = build()
    console.print(f"site written to {index.parent}")
    if open_site:
        webbrowser.open(index.resolve().as_uri())


@app.command()
def doctor():
    """Check keys and connectivity: LLM models, Crustdata, neatlogs."""
    from . import llm
    from .coach import ask_neatlogs

    obs.setup(tags=["mode:doctor"])
    for provider, (_, key_env, _) in {**llm.PROVIDERS, "bedrock": (None, "AWS_BEARER_TOKEN_BEDROCK", None)}.items():
        state = "[green]key set[/green]" if llm.provider_ready(provider) else "[dim]no key[/dim]"
        console.print(f"{provider:<10} {key_env:<26} {state}")
    console.print(f"{'crustdata':<10} {'CRUSTDATA_API_KEY':<26} {'[green]key set[/green]' if settings.crustdata_api_key else '[red]missing[/red]'}")
    console.print(f"{'neatlogs':<10} {'NEATLOGS_API_KEY':<26} {'[green]key set[/green]' if settings.neatlogs_api_key else '[red]missing[/red]'}")

    console.print("\n[bold]Model chains[/bold] (first working model is used; the rest are fallbacks)")
    for role, chain in (("smart", settings.models_smart), ("fast", settings.models_fast)):
        for spec in chain:
            if not llm.provider_ready(llm.split_model(spec)[0]):
                console.print(f"  {role:<5} {spec}: [dim]skipped (no key)[/dim]")
                continue
            try:
                text = llm.call(spec, "Reply with a JSON object {\"ok\": true}.", "ping (json)", None, 64)
                console.print(f"  {role:<5} {spec}: [green]ok[/green] {text.strip()[:30]!r}")
            except Exception as e:
                console.print(f"  {role:<5} {spec}: [red]{type(e).__name__}[/red] {str(e)[:160]}")

    if llm.provider_ready("gemini"):
        try:
            names = [m.id for m in llm._client("gemini").models.list()]
            flash = sorted(n.removeprefix("models/") for n in names if "flash" in n or "pro" in n)
            console.print(f"  gemini models available: {', '.join(flash[:20])}")
        except Exception as e:
            console.print(f"  gemini model list failed: {e}")

    if settings.crustdata_api_key:
        from .tools.crustdata import balance

        left = balance()
        console.print(f"  crustdata: {'[green]ok[/green] ' + format(left, ',.1f') + ' credits left' if left is not None else '[red]could not read balance[/red]'}")

    found = ask_neatlogs([])
    console.print(f"  neatlogs MCP: {'[green]ok[/green] ' + found.get('whoami', '')[:200] if found else '[red]not reachable[/red]'}")


if __name__ == "__main__":
    app()
