# Proyecto — Emergency Control

El diseño interno de la IA lo escribe usted en [`design.md`](design.md) **antes**
de implementar. Ese archivo ya trae las subsecciones que debe completar
(estado, acciones, `DROP`, batería, tamaño del espacio). El enunciado está en
el `README.MD` de la raíz; las reglas del mundo, en [`../CONTRATO.md`](../CONTRATO.md).

## Estructura

```text
project/
├── frontend/          # React + R3F — simulación 3D voxel
├── backend/           # FastAPI — POST /api/solve (agente de búsqueda)
├── scenarios/         # scenario.json — fuente de verdad
├── design.md
└── README.md
```

## Cómo levantar el proyecto

Abre **dos terminales**.

### Terminal 1 — Backend

```bash
cd project/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --app-dir src --reload --port 8000
```

Comprobar: http://127.0.0.1:8000/api/health

### Terminal 2 — Frontend

```bash
cd project/frontend
npm install
npm run dev
```

Abrir: http://localhost:5173

Pulsa **EXECUTE PLAN**. El frontend llama a `/api/solve` mediante el proxy de
Vite y reproduce el plan casilla a casilla.

El endpoint usa `agent.py`. El agente construye estados canónicos, genera
acciones legales, aplica poda de dominancia de batería y traduce las acciones
internas al contrato visual. El plan demo permanece en `demo_plan.py` solo como
referencia y prueba del simulador.

### Pruebas del agente

```bash
cd project/backend
source .venv/bin/activate
python tests/test_agent.py
python tests/test_demo_plan.py
```

Las pruebas verifican legalidad del plan, estados equivalentes, información
relevante, rutas alternativas, costos y el caso sin solución.

### Respuesta de la API

`POST /api/solve` recibe un escenario JSON y devuelve:

```json
{
	"solution_found": true,
	"total_cost": 99,
	"steps": [],
	"message": "...",
	"optimality_certified": false
}
```

`steps` solo contiene las operaciones visuales `MOVE`, `PICKUP`, `DROP` e
`INTERACT`. Si no existe solución, devuelve `solution_found: false` y
`steps: []`. La respuesta puede indicar `optimality_certified: false` cuando
se alcanza el límite de expansiones configurado para proteger el backend.

## Contrato visual vs agente (importante)

La versión oficial y completa de este contrato (esquema JSON, acciones de `INTERACT`, reglas del mundo y costos) está en `../CONTRATO.md`, que forma parte del enunciado.

El enunciado fija **4 operaciones visuales** que el frontend entiende:

```text
MOVE | PICKUP | DROP | INTERACT
```

`REPAIR`, `ACTIVATE`, `OPEN_DOOR`, `RECHARGE` **no son ops del plan de alto nivel**: son el campo `action` dentro de un paso `INTERACT`.

Ejemplo de lo que debe devolver `/api/solve`:

```json
{ "op": "INTERACT", "target": "PANEL_A", "action": "REPAIR", "consumes": "FUSE", "cost": 2 }
```

- **Agente (estudiante):** puede modelar acciones internas (`REPAIR_PANEL_A`, etc.) y luego **traducirlas** a `MOVE`/`PICKUP`/`DROP`/`INTERACT`.
- **Frontend / banco de pruebas:** solo ejecuta esas 4 ops. El log muestra `INTERACT REPAIR ...` para dejar claro el `op` + el `action`.

Así no hay contradicción: la capa visual no define la IA; solo anima el plan ya traducido.
