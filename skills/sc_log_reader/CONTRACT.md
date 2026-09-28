# Runtime contract

- Wingman module: `skills.sc_log_reader.main`; class: `SCLogReader`.
- `SCLogReader2` remains a Python alias. Profiles with that old enabled-skill
  name must re-enable `SCLogReader`; the alias cannot migrate discovery settings.
- Catalog discovery loads the registration wrapper; dependencies initialize
  when the host constructs the skill.
- This dependency bundle targets Windows x64 CPython 3.11. Other platforms
  require their own native dependency build and qualification.
- Observed log events, inferred state, requests, and confirmed outcomes are
  distinct. Missing or ambiguous evidence must not become confirmed money,
  ownership, inventory, or successful actions.
- Ship-channel changes describe player entry/exit observations, not nearby
  traffic or sensor detections.
- Runtime history and downloaded instructions belong in the configured
  Runtime Directory, outside the distributed skill.
- Valid instruction updates stage automatically and activate on a later
  process startup. Recovery preserves previous/bundled fallbacks and rejects
  a reverted revision. Python code is not downloaded by this updater.
- Accountant integrations consume the event database and its source identity.
  A change of source identity must not silently continue the previous cursor.

This contribution was assembled from the existing local 0.5.1 runtime. The
minimal file selection and native dependency import have separate checks;
they do not establish end-to-end behavior on the latest Wingman develop branch.
