# Methods, evidence and validation

f1verse distinguishes observations, descriptive estimates, parameter scenarios
and forecast evaluation. A change in a number after an event is not by itself
the causal effect of that event. All runtime code remains standard-library only.

## Evidence contract

Derived event, pace, survival and projection reports include an input hash,
method/version, library version, deterministic run ID, sample unit/count,
assumptions, exclusions and uncertainty type. A scenario range, conditional
filter standard deviation and calibrated prediction interval are different
objects and are labelled separately. Unknown quantities remain null with reasons.

The input hash identifies supplied data, not historical data nobody fetched.
The revision journal only records changes this installation observed. Events
separate `observed_at` (source fetch time) from `occurred_at` (when supplied);
lap-resolved ordering cannot resolve the order of events within the same lap.

Stable event IDs identify an event by session, kind, lap and participants.
Content revisions have separate hashes. Replayed duplicates collapse; conflicting
versions are reported. A changed lap changes event identity; cross-lap correction
matching is not inferred. Source references and availability remain inspectable.

## Event importance and pace shifts

`race.events()` joins observed timeline and pit-cycle changes. A measured gap
gain is an observed comparison, not an isolated undercut effect: weather,
traffic, tyre choice and an opponent's response can also explain it. Exchanges
crossing neutralised laps are excluded.

`race.turning_points()` ranks candidates by explicit event-kind weights. These
weights are editorial heuristics, not learned win probabilities. `pace_changes`
removes a median adjacent-lap trend, compares neighboring window medians, and
requires both an absolute threshold and a three-MAD noise floor. Windows do not
cross stint, missing-lap or excluded-lap boundaries. Conflicting duplicate laps
are omitted. This is retrospective detection, not online detection; thresholds
are not p-values. A detected change has no inferred cause.

## Fuel, wear and era limits

The legacy 110 kg / 1.6 kg per lap / 0.032 s per kg correction is an illustrative
scenario, not a measurement of a driver's fuel load. `stint_degradation` and
`tyre_outlook` decline corrected wear for 2026 onward without a caller-supplied
`fuel_model`. Clean raw trends remain available. Custom coefficients are labelled
caller scenarios, not calibrated models. Sensitivity to assumed fuel burn is
reported as a parameter range, not a confidence interval.

Pit, SC/VSC, restart, red-flag and conspicuously slow laps are excluded by
default. The slow-lap filter is a heuristic and cannot remove all traffic or
identify all energy-deployment effects. Tyre-outlook uncertainty is conditional
filter uncertainty; its constant-trend time to a threshold is not physical tyre
life. Pit timing is an endogenous strategy choice, not an independent observation
of the tyre's failure time. Unknown 2026 energy/aero modes are not reconstructed
from speed or the obsolete DRS channel.

## Survival and independent units

`retirement_risk` computes Kaplan-Meier survival for all-cause DNF flags over
completed-lap exposure in supplied settled races. Finishers are administratively
censored; DNS and DSQ rows are excluded. Missing DNF/exposure values and unfinished
sessions are reported, not zeroed. Duplicate sessions are not extra samples.

This describes the sample and relies on censoring/comparability assumptions.
Accident and mechanical causes are unavailable. Race lengths and conditions vary;
starts within a race share shocks and are dependent. The curve is neither a causal
estimate nor a calibrated prediction of an individual driver's future reliability.

## Forecast evaluation

`backtest_projection(checkpoints=[4, 8, 12])` reconstructs forecasts using form
and standings only through each cutoff. It scores multiclass Brier (sum over
labels), clipped log loss and calibration against a uniform baseline over the
same field. Central 80% point intervals are checked for empirical coverage,
width and interval score. Incomplete or failed cases are listed and excluded
from the common scoring set. No passing verdict is produced for an empty set.

Multiple cutoffs in a season are dependent. These are retrospective replays of
current corrected data and the current calendar, not timestamped issued forecasts.
The simulations are model scenarios; bootstrap variation is not proof of
calibration. Predictions conditional on a modelled field name omitted drivers.
Mathematical title eligibility remains a separate arithmetic result.

`forecast_scores` can also score separately persisted race/title probabilities.
Its caller must ensure time separation. Default grid base rates exclude the
forecast season and circuit conversion excludes races after the cutoff.

## Grounded narration

`fact_catalog(facts)` binds stable claim IDs to deterministic sentences and
fact-sheet paths. Generation selects IDs as JSON; Python combines names, values
and units. `verify` also accepts a limited grammar of exact fact-bound phrases
for existing callbacks. Token membership alone is insufficient. Unknown claims,
reassigned values, extra prose and unknown IDs are rejected; at most two attempts
precede the deterministic fallback. Cache hits undergo the same verification.
This is not a semantic verifier for arbitrary natural language.

## Cross-checking and access

Internal invariants and OpenF1 cross-endpoint comparisons are labelled as such;
two endpoints backed by the same origin are not two independent origins. No
complete sector tuples means the sector check is skipped, not passed. Access
failures, missing optional feeds, stale fallback and incomplete checks are visible.
Publication requires lifecycle, completeness, required inputs and checks to agree.
The report names its scope: the whole race story versus a non-race classification.

## Scientific references and implementation boundary

The following are methodological references, not runtime dependencies or claims
that their algorithms have been validated on F1:

- [Kloppy](https://kloppy.pysport.org/user-guide/getting-started/) and
  [OpenBB standardization](https://docs.openbb.co/odp/python/developer/standardization):
  normalize provider representations while preserving source-specific meaning.
- [socceraction VAEP](https://socceraction.readthedocs.io/en/latest/documentation/valuing_actions/vaep.html)
  and [nflfastR](https://nflfastr.com/): state-value changes motivate event analysis.
  f1verse's fixed event ranking is not an implementation of either value model.
- [ruptures](https://github.com/deepcharles/ruptures) and
  [River](https://github.com/online-ml/river): distinguish retrospective segmentation
  from predict-then-update online evaluation.
- [lifelines](https://lifelines.readthedocs.io/en/latest/Survival%20analysis%20with%20lifelines.html):
  censoring and time-at-risk; tyre-life identification is not implemented.
- [StatsForecast cross-validation](https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/crossvalidation.html),
  [MAPIE](https://mapie.readthedocs.io/en/stable/content/conformal-prediction/) and
  [Gneiting & Raftery](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf):
  time-held-out proper scoring and interval assessment. No conformal coverage
  guarantee is claimed: exchangeability can fail across eras and conditions.
- [DoWhy](https://www.pywhy.org/dowhy/v0.14/user_guide/refuting_causal_estimates/index.html),
  [CausalPy](https://github.com/pymc-labs/CausalPy),
  [GeoLift](https://github.com/facebookincubator/GeoLift) and
  [CausalML](https://github.com/uber/causalml): define treatment, outcome and
  estimand; check placebo interventions, overlap, spillover and confounding.
  f1verse does not turn observational pit-cycle comparisons into causal effects.
- [Meridian](https://developers.google.com/meridian/mmm),
  [Robyn](https://facebookexperimental.github.io/Robyn/docs/analysts-guide-to-MMM/),
  [PyMC-Marketing](https://github.com/pymc-labs/pymc-marketing) and
  [GrowthBook](https://docs.growthbook.io/statistics/cuped): explicit assumptions,
  experiment calibration, regularization and uncertainty. Marketing MMM, CLV,
  uplift and A/B assignment are outside this F1 library's API.
- [Frictionless Table Schema](https://specs.frictionlessdata.io/table-schema/),
  [OpenLineage](https://github.com/OpenLineage/OpenLineage/blob/main/spec/OpenLineage.md),
  [Datasette](https://docs.datasette.io/en/stable/) and
  [pretix](https://docs.pretix.eu/dev/api/webhooks.html): inspectable contracts,
  lineage, distinction between notifications and state, and duplicate-safe replay.

## Reproduction

Run `pytest -q --offline` for known-answer synthetic tests: constant trends,
persistent steps, isolated outliers, missing-lap boundaries, duplicate/revised
events, known survival curves, proper scores and failed forecast cases. These
prove mechanics and selected failure behavior, not real-world predictive skill.
Use `pytest -q` for source-backed integration checks. No dataset is bundled.
