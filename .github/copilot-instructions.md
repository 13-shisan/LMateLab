# AI Coding Agent Instructions for LMateLab

## Project Overview
LMateLab is a full-stack application with the following structure:

- **Backend**: Python-based, includes services for authentication, database management, and task processing. Key components:
  - `auth.py`, `authz_db.py`: Handle authentication and authorization.
  - `celery_app.py`: Manages asynchronous tasks using Celery.
  - `database.py`, `models.py`: Define database connections and ORM models.
  - `routers/`, `services/`, `tasks/`: Organize API routes, business logic, and background tasks.
- **Frontend**: React-based, built with Vite for fast development. TailwindCSS is used for styling.
- **Nginx**: Acts as a reverse proxy for serving the frontend and backend.

## Developer Workflows

### Backend
- **Run the application**:
  ```bash
  python backend/main.py
  ```
- **Start Celery worker**:
  ```bash
  chmod +x backend/start_worker.sh
  ./backend/start_worker.sh
  ```
- **Database migrations**:
  Use Alembic for migrations:
  ```bash
  alembic upgrade head
  ```
- **Install dependencies**:
  ```bash
  pip install -r backend/requirements.txt
  ```

### Frontend
- **Start development server**:
  ```bash
  npm install
  npm run dev
  ```
- **Build for production**:
  ```bash
  npm run build
  ```

### Docker
- **Build and run services**:
  ```bash
  docker-compose -f docker-compose.prod.yml up --build
  ```

## Project-Specific Conventions

- **Backend**:
  - Use FastAPI for API development.
  - Follow the folder structure for modularity: `routers/` for endpoints, `services/` for business logic, `tasks/` for background jobs.
  - Use `.env` files for environment-specific configurations.
- **Frontend**:
  - Use React functional components and hooks.
  - TailwindCSS is the primary styling framework.
  - ESLint and Prettier are configured for code quality.

## Integration Points

- **Database**: PostgreSQL is used as the primary database. ORM models are defined in `backend/models.py`.
- **Task Queue**: Celery is used for background tasks, with Redis as the message broker.
- **API Communication**: The frontend communicates with the backend via REST APIs.
- **Docker**: Both frontend and backend are containerized for production deployment.

## Key Files and Directories

- `backend/main.py`: Entry point for the backend application.
- `frontend/src/`: Contains React components and pages.
- `docker-compose.prod.yml`: Defines production services.
- `nginx/default.conf`: Nginx configuration for reverse proxy.

## Examples

### Adding a New API Endpoint
1. Create a new file in `backend/routers/`.
2. Define the endpoint using FastAPI:
   ```python
   from fastapi import APIRouter

   router = APIRouter()

   @router.get("/example")
   async def example_endpoint():
       return {"message": "Hello, World!"}
   ```
3. Include the router in `backend/main.py`.

### Adding a New React Page
1. Create a new file in `frontend/src/pages/`.
2. Define the component:
   ```jsx
   import React from 'react';

   const ExamplePage = () => {
       return <div>Hello, World!</div>;
   };

   export default ExamplePage;
   ```
3. Add a route in `frontend/src/App.jsx`.

---

This document is a starting point. Update it as the project evolves.