---
title: 'OpenCorpFilings API stability policy'
description: 'Understand versioning guarantees for the Python API, CLI and download manifests, and the limits for experimental source routes.'
---

# Stability

Version 1.0 makes a compatibility promise.

## What is promised

Until version 2.0, a minor or patch release does not remove or rename:

- the names in `opencorpfilings.__all__`;
- their parameters;
- the fields they return;
- the `ocf` commands and their JSON keys;
- the download manifest format;
- the error classes.

Additions arrive in minor releases and fixes in patch releases.

## What is outside the promise

- **What a regulator returns.** A source can change its site or API, and the
  affected route may fail until a release adapts to it.
- **Passed-through source fields:** the contents of `provider_metadata` and
  `provenance.raw` (also `filing.raw`), which carry whatever the source
  returned.
- **Experimental and limited routes.** Korea, the ES, NL, DK, SE, PL and FI
  national routes, and the ESEF index may change, be promoted or be removed
  in a minor release. See [tiers](markets/index.md#tiers).
- **`FilingProvider`**, a provisional extension point for adding a route. Its
  hook methods may change in a minor release.

## Checking what you have

```python
import opencorpfilings

opencorpfilings.__version__        # '1.1.1'
```

```bash
ocf --version                      # ocf 1.1.1
```

The public names and their signatures are listed in the
[API reference](reference/api.md), which is generated from the package; a test
fails when it drifts. Changes are recorded in the [changelog](reference/changelog.md).
Report problems in the repository's
[issue tracker](https://github.com/sourcestate-io/opencorpfilings/issues).
