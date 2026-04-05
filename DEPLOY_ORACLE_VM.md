# Oracle VM Deployment

This setup runs the VL calendar in Docker and mounts it at `https://assignsheet.com/vlcalendar` behind the existing Caddy site that is already serving `assignsheet.com`.

## What you need

- An Oracle Cloud VM with a public IPv4 address
- DNS control for `assignsheet.com`
- Docker Engine + Docker Compose plugin on the VM
- A production `.env.production` file
- Your SSH private key: `ssh-key-2026-03-28.key`
- The existing `Assignment Sheet 3.0` stack must remain online

## 1. Find the Oracle VM public IP

Use either of these:

- Oracle Console: `Compute` -> `Instances` -> your VM -> copy `Public IP Address`
- From the VM itself after SSH: `curl -4 ifconfig.me`

If you do not know the SSH username, Oracle images commonly use `opc` or `ubuntu`.

## 2. SSH into the server

On your Windows machine in PowerShell:

```powershell
icacls .\ssh-key-2026-03-28.key /inheritance:r
icacls .\ssh-key-2026-03-28.key /grant:r "$($env:USERNAME):(R)"
ssh -i .\ssh-key-2026-03-28.key opc@YOUR_ORACLE_PUBLIC_IP
```

If `opc` fails, try:

```powershell
ssh -i .\ssh-key-2026-03-28.key ubuntu@YOUR_ORACLE_PUBLIC_IP
```

## 3. Install Docker on the VM

Skip this if Docker is already installed. For Oracle Linux / Ubuntu, the simplest path is Docker's official install script:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

## 4. Copy the project to the VM

From your Windows machine:

```powershell
scp -i .\ssh-key-2026-03-28.key -r . ubuntu@YOUR_ORACLE_PUBLIC_IP:~/vlcalendar
```

Then on the VM:

```bash
cd ~/vlcalendar
cp .env.production.example .env.production
```

Edit `.env.production` and set real secrets.

## 5. Required production env vars

At minimum set:

```env
SECRET_KEY=long-random-secret
DATABASE_PATH=/data/vacation_scheduler.db
FLASK_DEBUG=false
ZEN_API_KEY=...
ZEN_MODEL=gpt-5.4-nano
```

If you want Gmail API email sending, also set:

```env
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
GMAIL_FROM=South Bay ED VL Schedule <your-sender@assignsheet.com>
```

## 6. Oracle firewall / security list

Open these inbound ports:

- `22/tcp` for SSH
- `80/tcp` for HTTP
- `443/tcp` for HTTPS

If the VM also runs `ufw`, allow the same ports:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 7. DNS for assignsheet.com

The root domain is already pointed at the VM. No separate DNS record is needed for `/vlcalendar` because it is a path on the existing host, not a subdomain.

If you ever move the VM, keep the existing `A` records for `assignsheet.com` and `www.assignsheet.com` pointed at the Oracle VM public IP.

## 8. Google / Gmail adjustments

This app sends mail with the Gmail API, not just SMTP. In your Google Cloud project:

1. Enable the Gmail API.
2. Keep the OAuth client active and not deleted.
3. Make sure the refresh token belongs to the mailbox you want to send from.
4. Make sure `GMAIL_FROM` is actually allowed by that mailbox.

If you want mail from `assignsheet.com`, you usually also need:

- Google Workspace or a Gmail mailbox allowed to send as that domain
- SPF for your domain
- DKIM for your domain
- ideally a DMARC record

If that is not configured yet, use a working Gmail sender first, then switch the sender later.

## 9. Wire `/vlcalendar` into the existing Caddy site

On the VM, edit `~/Assignment Sheet 3.0/Caddyfile` and insert this block inside the existing `assignsheet.com { ... }` site before the root `reverse_proxy`:

```caddy
handle_path /vlcalendar* {
  reverse_proxy vlcalendar-app:5000 {
    header_up X-Forwarded-Prefix /vlcalendar
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
  }
}
```

This preserves the existing root site and only mounts the VL calendar at `/vlcalendar`.

## 10. Build and start

The app joins the existing `assignmentsheet30_default` Docker network so Caddy can reach it directly.

On the VM:

```bash
cd ~/vlcalendar
docker compose -f docker-compose.oracle.yml build
docker compose -f docker-compose.oracle.yml up -d
cd ~/Assignment\ Sheet\ 3.0
docker compose up -d caddy
```

Check the app locally on the VM:

```bash
curl -I http://127.0.0.1:5001
curl -I https://assignsheet.com/vlcalendar/
```

Check containers:

```bash
cd ~/vlcalendar
docker compose -f docker-compose.oracle.yml ps
docker compose -f docker-compose.oracle.yml logs -f app
```

And for the shared Caddy:

```bash
cd ~/Assignment\ Sheet\ 3.0
docker compose logs -f caddy
```

## 11. Updates later

When you deploy changes:

```bash
cd ~/vlcalendar
docker compose -f docker-compose.oracle.yml build
docker compose -f docker-compose.oracle.yml up -d
cd ~/Assignment\ Sheet\ 3.0
docker compose up -d caddy
```

## 12. Backups

Your SQLite database lives in the Docker volume mounted at `/data/vacation_scheduler.db`.

Back it up periodically:

```bash
docker compose -f docker-compose.oracle.yml exec app cp /data/vacation_scheduler.db /data/vacation_scheduler.backup.db
```

For serious production use, copy backups off the VM as well.

## 13. What else you need

- A real `SECRET_KEY`
- A confirmed DNS setup for `assignsheet.com`
- Gmail API credentials that actually match the sending mailbox
- regular backups of the SQLite DB
- a plan to migrate from SQLite to Postgres later if concurrent write traffic grows

## Quick launch checklist

- VM has a public IP
- Ports `22`, `80`, and `443` are open
- DNS points `assignsheet.com` and `www.assignsheet.com` to the VM
- `.env.production` is filled in
- Docker and Compose are installed
- `docker compose -f docker-compose.oracle.yml up -d` succeeds in `~/vlcalendar`
- the existing `Assignment Sheet 3.0` Caddyfile includes the `/vlcalendar` handle block
