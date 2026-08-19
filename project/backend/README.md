# Backend — Emergency Control

FastAPI backend that exposes `POST /api/solve` and ejecuta el agente de búsqueda
definido en `src/agent.py`.

El endpoint recibe un escenario, construye el estado inicial, genera sucesores,
busca una solución y traduce el resultado al contrato visual. No se deben
modificar capacidad, batería ni zonas del escenario para forzar una solución.
La formulación de `Applicable` está documentada en `../design.md`.

## Run

```bash
cd project/backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --app-dir src --port 8000
```

Or from `backend/src`:

```bash
cd project/backend/src
uvicorn main:app --reload --port 8000
```

## Tests

```bash
cd project/backend
python tests/test_agent.py
python tests/test_demo_plan.py
```

## Respuesta y limitación conocida

La respuesta conserva el contrato:

```json
{
	"solution_found": true,
	"total_cost": 99,
	"steps": [],
	"optimality_certified": false
}
```

El plan devuelto se valida contra el simulador. El agente usa UCS con poda por
dominancia y un límite de expansiones para evitar consumo indefinido de
memoria. Si alcanza ese límite, retorna el mejor plan válido conocido y marca
`optimality_certified` como `false`.
