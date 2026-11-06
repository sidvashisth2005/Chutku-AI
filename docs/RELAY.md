# The phone app and your account

One ID and password connect your assistant on the laptop with the phone app. You create them once during setup. After
that both stay signed in until you log out on that device.

```
phone app (APK)  --https-->  relay (your server)  <--https, long poll--  laptop (Chutku)
```

## 1. Run the relay

The relay is a small Python server (`chutku/relay/server.py`, standard library only). It stores accounts as scrypt
hashes and forwards each phone request to that account's own laptop.

**At home only** (the phone on the same Wi-Fi as the laptop):

```
Start-Relay.cmd
```

It listens on port 8780. Windows asks once whether to allow it on private networks: say yes. The address is
`http://<laptop-IP>:8780`, for example `http://192.168.1.20:8780`. Find the IP with `ipconfig`.

**From anywhere:** run it on a server you control, behind HTTPS:

```
python -m chutku.relay --port 8780 --db /var/lib/chutku/relay.sqlite3
```

Put a TLS proxy in front of it (Caddy: `relay.example.com { reverse_proxy 127.0.0.1:8780 }`), or pass
`--tls-cert` and `--tls-key`.
- The laptop refuses a plain `http://` relay unless it is on this PC or your home network.
- Back up the database file: it holds the accounts.

## 2. Set up the laptop

```
.venv\Scripts\python.exe -m chutku.cli setup
```

Question 6 sets up the phone app:
1. Enter the relay address.
2. Create an ID and password. An ID that already exists is refused; choose another.
3. Choose a 4-6 digit phone PIN. The phone asks for it before approvals, screen view and control.

The address and the ID go into `.env`. The password is never stored. This laptop's sign-in token is kept in Windows
Credential Manager.

To change things later on the laptop:
- `chutku.cli account change` changes the ID and/or password. A new password signs the phone out.
- `chutku.cli account pin` changes the phone PIN.
- `chutku.cli account status` shows whether this laptop is signed in.
- `chutku.cli account logout` signs this laptop out.
- `chutku.cli account login` signs it back in.

## 3. Install the phone app

1. Copy `dist\Chutku-phone-1.0.apk` to the phone. To build it again, run `android\gradlew assembleRelease` with
   JDK 17+ and the Android SDK.
2. Open the file on the phone and allow installing from this source.
3. In the app, enter the relay address, then the same ID and password.

The app shows chat, hold-to-talk, the live screen, the trackpad, keyboard, files and "Laptop pe awaaz". Replies and
approval questions are spoken on the phone.

To bake your relay address into the app: `android\gradlew assembleRelease -PrelayUrl=https://relay.example.com`.

## Security, honestly

- **Passwords:** stored only as scrypt hashes. 5 wrong passwords lock the ID for 15 minutes.
- **Tokens:** random, stored only as SHA-256 hashes. They last until logout or a password change.
- **Kept apart:** a phone's requests reach only its own account's laptop. Phones cannot collect requests, and laptops
  cannot send them.
- **On the laptop**, every forwarded request goes through the phone server's usual rules:
  - the PIN for approvals, the screen and control;
  - laptop-only steps (R4, power, deleting for good, running code);
  - direct control must be armed at the laptop, and a red border shows.
- **What the relay can see:** the traffic it forwards, including screen frames, because TLS ends at the relay. Run it
  yourself, on a server you trust. End-to-end encryption between phone and laptop is a planned improvement.
- **The APK** is signed with the Android debug key so it installs at once. Sign it with your own key before publishing
  it anywhere.
