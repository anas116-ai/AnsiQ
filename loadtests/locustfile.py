"""Locust load testing for AnsiQ SaaS API."""

import random

from locust import HttpUser, between, task


class AnsiQApiUser(HttpUser):
    wait_time = between(0.5, 3.0)
    host = "http://localhost:8000"
    token = ""

    def on_start(self):
        resp = self.client.post("/api/auth/login", json={
            "email": "loadtest@ansiq.ai",
            "password": "loadtest",
        })
        if resp.ok:
            data = resp.json()
            self.token = data.get("access_token", "")

    @task(3)
    def health_check(self):
        self.client.get("/health", name="health")

    @task(2)
    def list_agents(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client.get("/api/agents", headers=headers, name="list_agents")

    @task(1)
    def create_agent(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client.post("/api/agents", json={
            "name": f"loadtest-agent-{random.randint(1, 10000)}",
            "role": "Tester",
            "goal": "Test performance",
            "backstory": "Automated load test agent.",
        }, headers=headers, name="create_agent")

    @task(1)
    def run_task(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client.post("/api/tasks", json={
            "description": "Perform a quick analysis",
            "expected_output": "Summary",
        }, headers=headers, name="create_task")
