# Owner steps: the public releases repository (one time)

The code repository `sidvashisth2005/Chutku-AI` stays **private**. Users download only from a separate **public**
repository, `sidvashisth2005/Chutku-releases`, which holds GitHub Releases and nothing else. The cloud session could not
create it (its GitHub access is limited to the code repository), so these steps are yours.

## 1. Create the public repository
1. On GitHub: **New repository** → name `Chutku-releases`, owner `sidvashisth2005`, **Public**.
2. Tick "Add a README file" (optional: paste `installer/README_PUBLIC.md` into it later).
3. No code, no workflows: it only receives releases.

## 2. A token that may publish there, and nothing else
1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Resource owner: `sidvashisth2005`. Repository access: **Only select repositories → `Chutku-releases`**.
3. Permissions → Repository permissions → **Contents: Read and write**. Nothing else.
4. Expiration: your choice (for example 1 year); you will repeat this step when it expires.
5. Copy the token (it is shown once).

## 3. Give it to the private repository's workflow
1. `sidvashisth2005/Chutku-AI` → **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `RELEASES_TOKEN`. Value: the token. Save.

Without this secret the release workflow builds and tests everything and then stops at "Publish" with:
`RELEASES_TOKEN is not set ... Nothing was published.`

## 4. Optional: sign the setup
Without a certificate the setup is unsigned: Windows SmartScreen shows "Windows protected your PC". Users click
**More info → Run anyway**. To sign, add two more secrets with a code-signing certificate:
- `CHUTKU_SIGN_PFX_BASE64`: the `.pfx` file, base64-encoded (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`);
- `CHUTKU_SIGN_PASSWORD`: its password.

`installer/sign.ps1` then signs `ChutkuSetup.exe`, and verifies the signature.

## 5. Make a release (after the PC session's Windows live checks)
```powershell
git tag v1.0.0
git push origin v1.0.0
```
The `release` workflow then:
1. runs the tests;
2. builds the package and checks it;
3. builds and checks the setup (a clean-machine install test);
4. publishes `ChutkuSetup.exe`, `Chutku-1.0.0-win64.zip`, its `.sha256` and `latest.json`.

`ChutkuSetup.exe` always installs what `releases/latest/download/latest.json` names, checked by SHA-256.
