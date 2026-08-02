## Frontend setup on Raspberry Pi

Frontend setup and production builds are performed manually.

### Install Node Version Manager (NVM)

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.6/install.sh | bash
```

Disconnect and reconnect the Secure Shell (SSH) session, then verify:

```bash
nvm --version
```

### Install Node.js

The required Node.js version is defined in the repository `.nvmrc` file.

```bash
cd ~/workspace/home-automation

nvm install
nvm use
```

Verify:

```bash
node --version
npm --version
```

### Install frontend dependencies

```bash
cd ~/workspace/home-automation/frontend

npm ci
```

### Build the production frontend

```bash
npm run build
```

The compiled frontend is created at:

```text
frontend/dist/
```

FastAPI serves this directory directly. A separate Node.js server does not run on the Raspberry Pi.

### Reduce disk usage after building

The production application does not require `node_modules`.

```bash
rm -rf node_modules
```

Before rebuilding the frontend later, restore the dependencies:

```bash
npm ci
npm run build
rm -rf node_modules
```

### Frontend development on macOS

```bash
cd frontend

nvm use
npm install
npm run dev
```

The Raspberry Pi backend must be running for relay commands from the development frontend to work.
