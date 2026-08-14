.PHONY: infra backend frontend eval test install

infra:
	docker compose up redis -d

install:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && . .venv/bin/activate && pytest -q

eval:
	cd backend && . .venv/bin/activate && python ../eval/run_eval.py

# UPDATE: add `make demo` that sets LLM_PROVIDER=openai and opens browser
