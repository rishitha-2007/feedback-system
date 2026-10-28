# Student Feedback Management System with CI/CD

## Run locally
    pip install -r requirements.txt && pytest
    docker compose up --build      # app :5000, Prometheus :9090, Grafana :3000
Logins: admin / admin123 (at /admin/login) · students 24CSE101–24CSE105 / student123

## Architecture
```mermaid
flowchart LR
  Dev[Developer / VS Code] --> GH[GitHub]
  GH --> GA[GitHub Actions: test]
  GA -->|pass| Build[Build Docker image] --> Hub[Docker Hub]
  Hub -->|pull| EC2[AWS EC2: docker compose]
  subgraph EC2
    Flask[Flask + Gunicorn] --> Mongo[(MongoDB)]
    Flask -->|/metrics| Prom[Prometheus] --> Graf[Grafana]
  end
  User[Student / Admin browser] --> Flask
```
Set GitHub secrets: DOCKERHUB_USERNAME, DOCKERHUB_TOKEN, EC2_HOST, EC2_KEY. Kubernetes is optional and not included.
