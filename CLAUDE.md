# mcp-memoria Project Rules & Conventions

## Behavioral Contract
Siempre que trabajes en este repositorio, debes priorizar la calidad, el orden y el control estricto de recursos físicos.

## Reglas Obligatorias de Razonamiento (Sequential Thinking)
- **Antes de modificar código o ejecutar comandos de shell**, debes utilizar la herramienta `sequentialthinking` del servidor `sequential-thinking` para estructurar tus razonamientos, analizar restricciones de hardware (RAM, CPU) y planificar la solución.
- Al menos 3-5 pensamientos de razonamiento secuencial son obligatorios para tareas no triviales.

## Flujo de Trabajo (Superpowers)
- **Antes de programar:** Debes crear un plan detallado en `implementation_plan.md` siguiendo la directriz del skill `writing-plans` (TDD completo sin placeholders).
- **Aprobación:** Detente y pide confirmación al usuario antes de ejecutar cualquier cambio en el código.
- **Ejecución:** Utiliza el skill `executing-plans` para implementar paso a paso, manteniendo el archivo `task.md` actualizado con el progreso real.
- **TDD Obligatorio:** Escribe primero la prueba unitaria fallida, verifícala en la terminal, escribe la solución mínima para que pase, y verifícala de nuevo antes de continuar.

## Restricciones del Servidor (secops)
- **RAM:** Servidor limitado (~11.6GB totales, swap activo de 3.8GB). Evitar levantar modelos de ML pesados de forma local (ONNX, fastembed, etc.).
- **Búsqueda Vectorial:** Utilizar llamadas API REST a Vertex AI (`text-embedding-004`) con credenciales ADC de `gcloud` y caché de token en memoria. No utilizar índices HNSW en MariaDB (consumen demasiada RAM).
- **Grafos:** No habilitar ni usar el motor OQGRAPH. Materializar listas de adyacencia como JSON nativo (`neighbors_json`) en la tabla `mm_entities` y resolver consultas a 1-hop en $O(1)$.

## Comandos Útiles
- Ejecutar pruebas: `pytest tests/ -v`
- Levantar servidor MCP local: `python -m memoria_mcp.server`
