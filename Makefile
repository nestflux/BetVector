# ===== BetVector Makefile =====
# Common commands for development and operation.

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
STREAMLIT := $(VENV)/bin/streamlit

.PHONY: install test run lint clean

# --- Create venv and install all dependencies ---
install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo ""
	@echo "✅ BetVector installed. Activate with: source $(VENV)/bin/activate"

# --- Run the full test suite ---
test:
	$(PYTHON) -m pytest tests/ -v

# --- Launch the Streamlit dashboard ---
run:
	$(STREAMLIT) run src/delivery/dashboard.py

# --- Lint with flake8 (install separately if needed) ---
lint:
	$(PYTHON) -m flake8 src/ --max-line-length 120 --ignore E501,W503

# --- Remove compiled files and caches ---
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
	@echo "✅ Cleaned."
