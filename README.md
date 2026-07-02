# CloudHub Explorer API

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-00a393.svg)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/uv-fast-ff0000.svg)](https://github.com/astral-sh/uv)

## Overview

The **CloudHub Explorer API** is a high-performance, unified backend service designed to orchestrate file management across multiple cloud storage providers. Built with **FastAPI** and **Python 3.11**, it provides a centralized interface for browsing, searching, and streaming media from services like **Google Drive** and **MEGA**.

This API serves as the backbone for the [CloudHub Explorer UI](https://github.com/rceus-platform/react-cloudhub-explorer-ui), enabling multi-account management and high-speed media delivery with range-request support.

## Key Features

- **Unified Cloud Integration**: Seamlessly browse files from Google Drive and MEGA in a single consolidated view.
- **Folder Merging**: Advanced logic to merge directory structures from different providers into a unified virtual filesystem.
- **Multi-Account Management**: Connect multiple accounts per provider (e.g., 5+ MEGA accounts, 10+ Google Drive accounts) simultaneously.
- **OAuth & Credential Management**: Secure handling of Google OAuth2 flows and MEGA session persistence.
- **Media Streaming Engine**: High-performance streaming for large video files, allowing instant seeking and smooth playback via range-request support.
- **Database Caching**: Persistent metadata caching using SQLAlchemy and SQLite for lightning-fast file lookups.
- **Security**: Unified access control layer via a secure site passcode.

## System Architecture

The application is structured to ensure high performance and maintainability:

- **FastAPI Backend**: Handles routing, authentication, multi-account orchestration, and API logic.
- **Node.js Sidecar Integration**: Utilizes a specialized Node.js sidecar ([node-mega-stream-service](https://github.com/rceus-platform/node-mega-stream-service)) for high-performance streaming, bypassing Python CPU bottlenecks during decryption (e.g., MEGA streaming).
- **SQLite + SQLAlchemy**: Relational database for storing metadata and caching file structures.

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Runtime**: [Python 3.11+](https://www.python.org/)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Database**: SQLite with [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/)
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Cloud SDKs**: `google-api-python-client`, `mega.py`

## Getting Started

### Prerequisites

- **Python**: 3.11 or higher
- **uv**: Astral's high-speed Python package manager (`pip install uv`)
- **Node.js**: v16+ (Required for the streaming sidecar)

### Installation

1. **Clone the repository:**

   ```bash
   git clone <repository_url>
   cd python-cloudhub-explorer-api/application-source
   ```

2. **Sync dependencies:**
   ```bash
   uv sync
   ```

### Configuration

Create a `.env` file in the `application-source` directory based on the provided `.env.example` template (do not commit this file to version control).

```env
# Security
SITE_PASSCODE=your_secure_passcode_here

# Google Drive OAuth (Requires GCP Console setup)
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here

# Optional: Default MEGA credentials for environment-based login
MEGA_USERNAME=your_mega_email@example.com
MEGA_PASSWORD=your_secure_mega_password_here

# Sidecar Configuration
SIDE_CAR_HOST=localhost
SIDE_CAR_PORT=4000
```

_Note: Ensure `.env` is listed in your `.gitignore` to prevent leaking sensitive credentials._

### Database Migrations (Alembic)

The project uses Alembic for database schema versioning. Before starting the API in any environment, ensure the database is up-to-date:

```bash
cd application-source
uv run alembic upgrade head
```

To create a new migration after making changes to the SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "describe_your_changes"
```

### Running the Services

For local development, you need to run both the Node.js sidecar and the Python API.

1. **Start the Node.js Sidecar:**

   ```bash
   # Clone and setup the sidecar repository
   git clone https://github.com/rceus-platform/node-mega-stream-service
   cd node-mega-stream-service
   npm install
   npm run build
   npm start
   ```

2. **Start the FastAPI Backend:**
   ```bash
   cd python-cloudhub-explorer-api/application-source
   uv run uvicorn app.main:app --reload --port 8000
   ```

The API documentation (Swagger UI) will be available at `http://localhost:8000/docs`.

## Project Structure

```text
application-source/
├── app/
│   ├── api/          # API Route definitions (auth, accounts, files)
│   ├── core/         # Global config, security, and dependencies
│   ├── db/           # Database models, schemas, and session management
│   ├── services/     # Cloud provider specific logic (GDrive, Mega)
│   ├── utils/        # Shared utilities (folder merging, file helpers)
│   └── main.py       # Application entry point & middleware config
├── tests/            # Pytest suite for API and service validation
├── pyproject.toml    # Project dependencies and tool configuration
└── uv.lock           # Deterministic dependency lockfile
```

## API Endpoints

| Category     | Endpoint                     | Description                              |
| ------------ | ---------------------------- | ---------------------------------------- |
| **Auth**     | `POST /auth/login`           | Authenticate and retrieve session tokens |
| **Accounts** | `GET /accounts/google/login` | Initiate Google OAuth flow               |
| **Accounts** | `POST /accounts/mega/login`  | Connect a new MEGA account               |
| **Files**    | `GET /files/`                | List files from all connected accounts   |
| **Files**    | `GET /files/stream`          | Stream file content with range support   |

---

_Built with precision for the modern cloud explorer._
