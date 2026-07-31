# Release checklist

MCPPool uses the package version in `src/mcp_pool/__init__.py` as its single version source.

1. Ensure `main` is green and `CHANGELOG.md` has no undocumented user-visible changes.
2. Run all backend, frontend unit, browser E2E, package, and container checks from
   `CONTRIBUTING.md`.
3. Build with `uv build` and verify the wheel and source archive in a clean environment.
4. Build both container images from the committed lockfiles and record their immutable digests.
5. Generate an SBOM for the Python artifacts and each image, scan dependencies and images, and
   retain the reports with the release.
6. Tag `vMAJOR.MINOR.PATCH`, create release notes from the changelog, publish immutable artifacts,
   and sign or attest each artifact through the selected release platform.
7. Perform the clean-room quickstart and rollback rehearsal before announcing the release.

Publishing credentials must be held by the release platform, not stored in this repository.
