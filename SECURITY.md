# Security policy

## Supported version

Security fixes are applied to the current `main` branch. Historical artifacts,
legacy experiment bundles and archived submissions are not supported runtimes.

## Reporting a vulnerability

Do not publish a vulnerability, competition-data leak, unsafe-query bypass or
credential exposure in a public issue. Contact the repository owner through a
private channel and include:

- affected commit and environment;
- minimal reproduction without proprietary data;
- impact on corpus confidentiality, query sandbox, artifact integrity or
  supply chain;
- suggested mitigation, if known.

The repository intentionally does not publish an email address that has not
been verified by the owner. Until a private security contact is configured on
the hosting platform, use its private vulnerability-reporting feature.

## Security boundaries

- Production ingestion, retrieval, execution and packaging are offline.
- Packaged Pandas expressions pass a restricted AST validator and execute with
  an allowlisted namespace.
- Paths in evidence and ZIP members are validated against traversal and orphan
  files.
- Runtime dependencies are hash-locked for acceptance work.
- Model artifacts are rejected unless their license, release date, parameter
  count and checksum satisfy `configs/models.yaml`.
- Secrets, credentials, private datasets, generated databases and submission
  ZIPs must not be committed.

No security claim extends to user-modified plugins, optional local model
servers or historical scripts outside the canonical CLI path.
