"""Local human-only update controls. No approval endpoint or AI tool exists."""

from pathlib import Path

from .updates import UpdateManager


def review_lines(status, *, host_mode=False):
    lines = [
        "Runtime folder: " + status["runtime_directory"],
        "Update publisher: " + (status.get("source_url") or "Not configured"),
        "Active version: " + status.get("active_version", "unknown"),
        "Scheduled version: " + status.get("staged_version", "None"),
        "Rollback target: " + status.get("rollback_version", "unknown"),
        "Rollback SHA-256: " + status.get("rollback_sha256", "unknown"),
    ]
    if status.get("staged_sha256"):
        lines += [
            "Scheduled SHA-256: " + status["staged_sha256"],
            "Scheduled change: " + (status.get("staged_kind") or "unknown"),
            "Scheduled publisher: "
            + (status.get("staged_source_url") or "Local rollback"),
        ]
    if status.get("sha256"):
        lines += [
            "Available version: " + status["candidate_version"],
            "SHA-256: " + status["sha256"],
            "Available publisher: "
            + (status.get("candidate_source_url") or "Unknown; download again"),
            "Requires reader: " + status["minimum_reader_version"],
            "Qualified game builds: "
            + (", ".join(status["verified_game_builds"]) or "Not yet qualified"),
            "",
            status["release_notes"],
        ]
    else:
        lines += ["No downloaded update is waiting for review."]
    if host_mode:
        lines += ["Activation: next Wingman process startup."]
        if (status.get("staged_boundary") or {}).get("kind") == "unresolved":
            lines += [
                "Process snapshot unavailable; an additional Wingman restart may be required."
            ]
    if status.get("skipped"):
        lines += ["You skipped this version. Newer versions will still be offered."]
    for name in ("rollback_fallback_reason", "activation_notice", "notice", "error"):
        if status.get(name):
            lines += [status[name]]
    return lines


def show_review(runtime_directory, url=None, *, host_mode=False):
    # Imported only by the explicitly launched CLI command, never by Wingman.
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    manager = UpdateManager(Path(runtime_directory) / "instructions", url)
    window = tk.Tk()
    window.title("Star Citizen Log Reader — instruction updates")
    window.geometry("900x600")
    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Reading instructions", font=("Segoe UI", 16)).pack(
        anchor="w"
    )
    startup = "Wingman process startup" if host_mode else "explicit standalone startup"
    ttk.Label(frame, text="Updates take effect at the next " + startup + ".").pack(
        anchor="w", pady=6
    )
    content = scrolledtext.ScrolledText(frame, height=16, wrap="word")
    content.pack(fill="both", expand=True)
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=12)
    shown_digest = None
    shown_source = None
    shown_generation = None
    shown_rollback = None
    shown_staged = None

    def refresh():
        nonlocal \
            shown_digest, \
            shown_source, \
            shown_generation, \
            shown_rollback, \
            shown_staged
        status = manager.status()
        shown_digest = status.get("sha256")
        shown_source = status.get("candidate_source_url")
        shown_generation = status.get("source_generation")
        shown_rollback = status.get("rollback_sha256")
        shown_staged = status.get("staged_sha256")
        lines = review_lines(status, host_mode=host_mode)
        content.configure(state="normal")
        content.delete("1.0", "end")
        content.insert("1.0", "\n".join(lines))
        content.configure(state="disabled")
        update.configure(state="normal" if shown_digest else "disabled")
        skip.configure(state="normal" if shown_digest else "disabled")
        cancel.configure(state="normal" if status.get("staged_sha256") else "disabled")

    def action(which):
        try:
            if which == "approve":
                manager.approve(
                    shown_digest,
                    source_url=shown_source,
                    source_generation=shown_generation,
                )
                messagebox.showinfo(
                    "Update approved",
                    "Scheduled for the next "
                    + startup
                    + ". An additional restart may be required if process lookup fails.",
                    parent=window,
                )
            elif which == "cancel":
                manager.cancel(
                    source_generation=shown_generation, expected_sha256=shown_staged
                )
            elif which == "skip":
                manager.skip(shown_digest, source_generation=shown_generation)
            else:
                result = manager.rollback(
                    expected_sha256=shown_rollback, source_generation=shown_generation
                )
                messagebox.showinfo(
                    "Rollback scheduled",
                    (
                        result.get("fallback_reason")
                        or "The previous instructions will be restored"
                    )
                    + " at the next "
                    + startup
                    + ".",
                    parent=window,
                )
            refresh()
        except (OSError, ValueError) as exc:
            refresh()
            messagebox.showerror(
                "Update unavailable",
                str(exc)
                + "\nThe display has been refreshed. Review it before clicking again.",
                parent=window,
            )

    update = ttk.Button(
        buttons, text="Update next startup", command=lambda: action("approve")
    )
    update.pack(side="left")
    ttk.Button(buttons, text="Later", command=window.destroy).pack(side="left", padx=6)
    skip = ttk.Button(buttons, text="Skip this version", command=lambda: action("skip"))
    skip.pack(side="left")
    cancel = ttk.Button(
        buttons, text="Cancel scheduled update", command=lambda: action("cancel")
    )
    cancel.pack(side="left", padx=6)
    ttk.Button(buttons, text="Roll back", command=lambda: action("rollback")).pack(
        side="right"
    )
    refresh()
    window.update_idletasks()
    window.mainloop()
