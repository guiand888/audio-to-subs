# Project Naming

The app family uses the umbrella brand **Parole** (French for "speech"),
with a `-<domain>` suffix per variant. This repo is the subtitles variant.

| App | Purpose | Binary |
|---|---|---|
| ParoleSub (`parolesub`) | Video → subtitles (this repo) | `parolesub` |
| ParoleCast (`parolecast`) | Podcast transcription | `parolecast` |
| ParoleNote (`parolenote`) | Voice memos / notes | `parolenote` |
| ParoleLive (`parolelive`) | Live / meeting captions | `parolelive` |

All variants share the Parole umbrella (repo group, backup, branding) and are
differentiated only by the suffix. New variants reuse the same backup/infra.

Rationale: "Parole" is short, ties to the French/EU roots of the project, and
reads cleanly as a prefix for any future transcription domain.
