### Changed

- needs-decision: a headless session's question about a failed command tells a denial, a delivery hook refusal, and a not-found (exit 127) apart, each with its own fix; a not-found's question names the program missing from the gate host's PATH and never proposes widening the allowlist (#1078)
