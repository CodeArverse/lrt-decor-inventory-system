# LRT Inventory - server setup

## 1. Try it on your own PC first
1. Copy `server.env.example` to `server.env` and fill it in (ADMIN_EMAIL is required).
2. (Optional) Copy your existing `inventory.db` into a folder named `data` next to `server.py`
   to keep your stock list. Without it, the server starts with the starting item list.
3. Run `python server.py`. On the first start it prints the **admin email + temporary password**.
4. Run the desktop app (`python main.py` in the client folder). `SERVER_URL` in `api.py`
   already points to `http://127.0.0.1:8000`.

## 2. Put it online (a small Linux server / VPS, Python 3.9+)
1. Copy the `server` folder to the VPS, e.g. `/opt/lrt-server`, and create `server.env` there.
   Add `HOST=127.0.0.1` so only the HTTPS proxy below can reach it.
2. Point a domain name (e.g. `inventory.yourdomain.com`) at the VPS.
3. HTTPS with Caddy (gets the certificate automatically). `/etc/caddy/Caddyfile`:

       inventory.yourdomain.com {
           reverse_proxy 127.0.0.1:8000
       }

   Open ports 80 and 443 in the VPS firewall.
4. Keep the server running: `/etc/systemd/system/lrt-inventory.service`

       [Unit]
       Description=LRT Inventory server
       After=network.target

       [Service]
       WorkingDirectory=/opt/lrt-server
       ExecStart=/usr/bin/python3 /opt/lrt-server/server.py
       Restart=always

       [Install]
       WantedBy=multi-user.target

   Then: `sudo systemctl enable --now lrt-inventory` and read the first admin password with
   `sudo journalctl -u lrt-inventory`.
5. **Back up the `data` folder** (inventory.db). Don't use hosting with a temporary disk
   (many free tiers) - the data would be wiped on restart.

## 3. The desktop app
Put the server address in `client/api.py` (`SERVER_URL = "https://inventory.yourdomain.com"`)
or in a file `server_url.txt` next to the .exe. Build as before:

    pyinstaller --noconsole --onedir --name "LRT Inventory" --add-data "pexels-kathlene-1676830-35493874.png;." main.py

The .exe no longer contains any database or Gmail password.
