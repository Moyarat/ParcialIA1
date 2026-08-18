# Diseño del agente

Este documento debe completarse **antes** de la implementación principal del agente.

Use sus propias palabras y notación. No reemplace este archivo por una transcripción
del enunciado. Las subsecciones existen para que no se le olvide una decisión;
usted decide el contenido.

El entorno, según las propiedades vistas en clase, es totalmente observable,
determinista, secuencial, estático, discreto y de agente único. Bajo esas
condiciones la solución es un **plan completo** y el marco correcto es la
búsqueda clásica. Justifique cada componente con ese marco (AIMA, cap. 3).

---

## Estado

### Definición formal

Escriba la tupla de estado. Cada componente debe ser una variable que el robot
necesita para saber qué podrá hacer después.

```text
s = ⟨ pos, bat, cargo, ground, env ⟩
```

(completar)

### Por qué cada variable es necesaria

Criterio de clase (`Applicable`): una variable pertenece al estado **si y solo si**
dos configuraciones que difieran en ella pueden diferir en las acciones legales
futuras o en su resultado.

Pase ese filtro con cada variable. En particular:

- pos (Posición del Robot): Condiciona directamente las acciones de movimiento legal (MOVE a zonas adyacentes), la recarga (RECHARGE solo en estaciones) e interacción con elementos situados en dicha zona (PICKUP, INTERACT). 
- bat (Batería Residual): Determina la legalidad de cualquier acción $a$ que consuma energía ($bat \ge cost(a)$). Dos estados idénticos que difieran en $bat$ difieren en qué secuencias de desplazamiento o retorno a estaciones de recarga son viables sin que el robot quede inoperativo
- cargo (Inventario en Transporte): Restringe la capacidad física restante ($cargo\_weight(cargo) + weight(o) \le cargo\_capacity$) y habilita las acciones de reparación o desbloqueo que exijan herramientas o materiales específicos.
- ground (Posición de Objetos en el Suelo): Dado que el agente puede soltar objetos (DROP) en cualquier zona, la ubicación de los elementos en el suelo no se deduce de la configuración inicial. Modifica directamente las precondiciones de PICKUP en cada zona
- env (Estado Persistente del Entorno): Registra los cambios irreversibles. Por ejemplo, desbloquear una puerta habilita la acción MOVE a través de ese corredor en ambos sentidos; activar el generador habilita la reparación de subsistemas dependientes. 


### Qué información se deriva y NO se almacena

- Peso actual de la carga: Se calcula dinámicamente como $\sum_{t \in cargo} \text{cantidad}(t) \times weight(t)$
- Grafo de conectividad del mapa y costos de corredores: Representa información constante e inmutable del problema
- Capacidad máxima ($cargo\_capacity$) y Batería máxima ($B_{max}$): Parámetros constantes de la instancia. 
- Ubicación estática de paneles y estaciones de recarga: Diccionarios fijos definidos en el mapa
### Qué pertenece al historial de búsqueda y no al estado físico

Existe una distinción fundamental entre la entidad Estado (situación física del mundo) y la entidad Nodo (estructura de datos del árbol de búsqueda):
- Pertenece exclusivamente al Nodo:
  * $g(n)$: Costo acumulado desde el estado inicial. 
  * $parent$: Referencia al nodo padre para la reconstrucción del plan. 
  * $action$: La acción interna que condujo a este nodo. 
  * $depth$: Profundidad en el árbol de búsqueda.

Si se incluyera $g(n)$ o el historial dentro del Estado, dos rutas que alcancen la misma configuración física tendrían representaciones lógicas distintas. Esto rompería el control de ciclos en el conjunto CLOSED (Graph Search), haciendo que el algoritmo explore indefinidamente la misma situación física alcanzada por caminos de costos diferentes, provocando explosión en memoria.

### Cuándo dos configuraciones son el mismo estado

De acuerdo con la especificación del escenario (§2.2), los materiales y herramientas del mismo tipo son físicamente equivalentes y no deben etiquetarse con IDs artificiales.
* Estructura Canónica:
   - $cargo$ y $ground[z]$ se representan mediante contadores por tipo de objeto (Counter o tuplas ordenadas de pares (tipo_objeto, cantidad)), omitiendo identificadores individuales.
  - El diccionario $ground$ se convierte a una tupla inmutable y ordenada alfabéticamente por zona: tuple(sorted((z, tuple(sorted(items.items()))) for z, items in ground.items())).  

* Igualdad y Hashing:
  Se garantiza que para dos instancias de estado $s_A$ y $s_B$, s_A == s_B y hash(s_A) == hash(s_B) retornen verdadero si y solo si la posición del robot, nivel de batería, inv. de carga, distribución de objetos en el suelo y estado del entorno son exactamente idénticos.  

### Relevancia: objetos que ya no cambian el futuro

Los cambios en el entorno son monótonos (ej. una puerta desbloqueada permanece abierta; un panel reparado no se vuelve a averiar).

* Regla de Poda de Relevancia (Objetos Inertes / "Muertos"):
  Si una herramienta $h$ se requiere únicamente para reparar el panel $P_1$, y $P_1$ ya ha sido reparado ($env[P_1] = True$), dicha herramienta deja de habilitar ninguna acción futura en todo el resto de la misión. 
* Acción del Agente: Cuando la condición $env[P_1] = True$ se cumple, el objeto $h$ se retira de la representación activa del estado ($ground$ o $cargo$). 
* Demostración de Preservación del Óptimo (Soundness):
  Dado que ninguna acción legal futura ni la condición de meta dependen de $h$, la posición de $h$ en el suelo no puede diferir en las acciones futuras ni en sus costos. Eliminarla del estado evita multiplicar el espacio por las permutaciones inútiles de trasladar un objeto que ya no sirve.

---

## Acciones

Las acciones internas del agente representan las operaciones físicas que el robot ejecuta en la simulación. Toda acción requiere $bat \ge \text{costo}$. 

| **Acción Interna** | **Precondiciones** | **Efectos** | **Costo** |
|---|---|---|---|
| **`MOVE(z_from, z_to)`** | $pos = z_{from} \land z_{to} \in Adj(z_{from}) \land (IsDoor(z_{from}, z_{to}) \implies env[door] = Unlocked) \land bat \ge cost(z_{from}, z_{to})$ | $pos \leftarrow z_{to}$, $bat \leftarrow bat - cost(z_{from}, z_{to})$ | Costo del corredor |
| **`RECHARGE()`** | $IsRechargeStation(pos) \land bat < B_{max} \land bat \ge cost_{recharge}$ | $bat \leftarrow B_{max}$, $bat \leftarrow bat - cost_{recharge}$ | $cost_{recharge}$ (costo de recarga) |
| **`PICKUP(obj_type)`** | $ground[pos][obj_{type}] > 0 \land cargo_{weight}(cargo) + weight(obj_{type}) \le cargo_{capacity} \land bat \ge cost_{pickup}$ | $ground[pos][obj_{type}] \leftarrow ground[pos][obj_{type}] - 1$, $cargo[obj_{type}] \leftarrow cargo[obj_{type}] + 1$, $bat \leftarrow bat - cost_{pickup}$ | $cost_{pickup}$ |
| **`DROP(obj_type)`** | $cargo[obj_{type}] > 0 \land IsUsefulDropZone(pos, obj_{type}) \land bat \ge cost_{drop}$ | $cargo[obj_{type}] \leftarrow cargo[obj_{type}] - 1$, $ground[pos][obj_{type}] \leftarrow ground[pos][obj_{type}] + 1$, $bat \leftarrow bat - cost_{drop}$ | $cost_{drop}$ |
| **`INTERACT_UNLOCK_DOOR(door_id)`** | $DoorAt(door_{id}, pos) \land env[door_{id}] = Locked \land RequiredKey(door_{id}) \in cargo \land bat \ge cost_{interact}$ | $env[door_{id}] \leftarrow Unlocked$, $bat \leftarrow bat - cost_{interact}$ (La llave/herramienta no se consume) | $cost_{interact}$ |
| **`INTERACT_REPAIR_PANEL(panel_id)`** | $PanelAt(panel_{id}, pos) \land env[panel_{id}] = Unrepaired \land RequirementsMet(panel_{id}, cargo, env) \land bat \ge cost_{interact}$ | $env[panel_{id}] \leftarrow Repaired$, consume los materiales requeridos de $cargo$, $bat \leftarrow bat - cost_{interact}$ | $cost_{interact}$ |

### `Applicable` interno vs legalidad del contrato

El simulador/contrato permite ejecutar DROP en cualquier zona donde el robot lleve carga. Sin embargo, si el generador de sucesores generara DROP de forma indiscriminada en cada zona, el espacio de estados pasaría de ser las 5 zonas del mapa a la combinatoria completa de dónde quedó ubicado cada objeto ($Z^N$). 

1. Restricción Óptima de DROP (IsUsefulDropZone):
   Un plan óptimo de menor costo nunca suelta un objeto en una zona intermedia arbitraria salvo bajo dos condiciones estrictamente útiles:
2. Zona de Aplicación Final: 
   La zona $pos$ requiere directamente el objeto $obj\_type$ para reparar un   panel en dicha zona, pero el robot debe realizar un intercambio de inventario.  Liberación Necesaria de Capacidad (Intercambio Pragmático): El inventario del robot está al límite de peso ($cargo\_weight \approx cargo\_capacity$), se requiere recoger un objeto indispensable $O_A$ ubicado en $pos$, y se suelta temporalmente un objeto $O_B$ en $pos$ para liberar capacidad.
Demostración de Preservación de Optimalidad:
En cualquier otra zona no relevante, soltar un objeto y luego volverlo a recoger acumula costos inútiles ($cost\_drop + cost\_pickup > 0$) sin aportar ningún beneficio a las acciones futuras ni a la meta. Por ende, ningún plan de costo mínimo utiliza una acción DROP fuera de estas condiciones. Omitirlas del generador de sucesores es una decisión sound y preserva la optimalidad
---

## Modelo de transición

```text
s  --a-->  s'     solo si a ∈ Applicable(s)
```

1. Transformación del Estado: Dada la acción $a$, se calcula explícitamente el nuevo valor de $pos$, la reducción de $bat$, el cambio en $cargo$ y $ground$, y la actualización de las variables booleanas en $env$.  
2. Canonicalización e Invariantes: Se aplica la ordenación canónica a las colecciones del nuevo estado $s'$ y se ejecuta la regla de poda de objetos inertes.  
3. Validación: Si $bat' < 0$ o $cargo\_weight(cargo') > cargo\_capacity$, la transición no produce sucesor ($Result(s, a) = \emptyset$).

---

## Prueba de meta

$$Goal(s) \iff \bigwedge_{p \in TargetPanels} (env[panel_p] == Repaired) \land \bigwedge_{s \in TargetSystems} (env[sys_s] == Active)$$

Las puertas desbloqueadas, las recargas realizadas y las herramientas recogidas son medios transitivos para alcanzar la restauración de la instalación. La misión tiene éxito si y solo si todos los sistemas críticos exigidos por la meta se encuentran activos y reparados en $env$.  


---

## Función de costo

```text
$$g(n) = \sum_{i=1}^{k} cost(a_i)$$
```

  donde $a_1, a_2, \dots, a_k$ es la secuencia de acciones desde el estado inicial hasta el nodo actual $n$.  Minimizar Pasos vs. Minimizar Costo:
  
  En este escenario los costos de movimiento son heterogéneos (existen corredores rápidos y caros, o lentos y baratos) y las operaciones físicas poseen costos distintos. Minimizar el número de pasos produciría planes subóptimos que eligen caminos cortos en pasos pero extremadamente costosos en batería. La función $g(n)$ garantiza la selección del plan con menor costo acumulado real
---

## Estrategia de búsqueda

Dado que los costos de las acciones son heterogéneos y positivos ($cost(a) > 0$) y se requiere el plan de costo acumulado mínimo, la estrategia seleccionada es Búsqueda de Costo Uniforme (UCS / Uniform Cost Search) (AIMA Cap. 3.4.2), equivalente al algoritmo de Dijkstra en grafos

Propiedades y Garantías:
   * Completitud: Garantizada en espacios de estados finitos donde todo costo de acción sea mayor que una constante estricta $\epsilon > 0$.  
   * Optimalidad: Garantizada siempre que la prueba de meta $Goal(s)$ se realice al extraer el nodo de la cola de prioridad (OPEN), y no al generarlo.  
   * Estructura de Datos (OPEN y CLOSED): 
      * OPEN: Cola de prioridad (Min-Heap) ordenada estrictamente por $g(n)$.  
      * CLOSED: Diccionario/Set de estados canónicos físicos ya extraídos.  

### Batería como recurso

Aunque la batería forma parte de la situación física (§2.1), explorar variaciones redundantes de batería provoca que UCS recorra "paseos de consumo de energía" inútiles. 
Criterio de Dominancia de Batería:
Si dos rutas alcanzan la misma configuración física del mundo ($pos, cargo, ground, env$) y el nodo $n_1$ llega con una batería $bat_1$ a un costo $g(n_1)$, mientras que el nodo $n_2$ llega con $bat_2$ a un costo $g(n_2)$, entonces $n_1$ domina a $n_2$ si y solo si: 

$$g(n_1) \le g(n_2) \quad \land \quad bat_1 \ge bat_2$$

Manejo en CLOSED:
En la lista CLOSED, para cada estado físico $(pos, cargo, ground, env)$, se almacena un registro con la mejor combinación observada: (best_g, max_battery). Cuando se genera un sucesor $s_{nuevo}$ cuya configuración física ya existe en CLOSED:
 * Si $g(s_{nuevo}) \ge best\_g$ y $bat(s_{nuevo}) \le max\_battery$, el nodo está estrictamente dominado y se descarta de inmediato.  
 * Esto corta de raíz los rodeos inútiles y evita que la búsqueda explote en memoria tratando cada nivel de batería como un mundo distinto.
---

## Formulación y tamaño del espacio (obligatorio)

1. ¿Por qué «5 zonas, ~10 objetos, capacidad 3» puede generar millones de nodos en un UCS ingenuo?
   Porque la combinación de ubicar 10 objetos en 5 zonas produce $5^{10} \approx 9.7 \times 10^6$ distribuciones posibles en el suelo. Multiplicado por las subcombinaciones del inventario ($\binom{10}{3}$), la posición del robot (5), los niveles de batería discretos y el estado del entorno ($2^K$), la combinatoria bruta supera los $10^9$ estados. 
2. ¿Qué papel tiene DROP en esa explosión?
   DROP es el generador directo de permutaciones de objetos en el suelo. Si en cada estado se permite soltar cualquier objeto en cualquier zona, UCS genera ramas infinitas donde el robot se dedica a cambiar elementos de habitación sin avanzar en la meta de la misión.  
3. ¿Qué podas o abstracciones aplicó y por qué NO pierden el óptimo (sound)?
   * Poda de DROP útil: Solo se genera DROP en zonas que requieren directamente el objeto o para liberar inventario ante un intercambio indispensable en la misma zona.
   * Poda de Relevancia de Objetos: Se eliminan del estado las herramientas pertenecientes a tareas ya completadas.
   * Canonicalización por Tipos: Agrupamiento de elementos equivalentes mediante contadores sin IDs.
   * Poda por Dominancia de Batería: Se descartan nodos con menor batería y mayor costo para la misma configuración del mundo.
   Ninguna de estas podas elimina un camino que pudiera formar parte de un plan de costo mínimo, manteniendo la búsqueda sound y óptima.
 4. ¿Por qué NO es solución subir la capacidad, bajar las estaciones o ignorar la batería?
    Porque alterar los parámetros físicos falsifica las reglas del entorno, violando el contrato del simulador y produciendo planes inviables en el banco de pruebas real del profesor. Además, aumentar la capacidad de transporte incrementaría la combinatoria del inventario, empeorando la explosión en lugar de resolverla. La solución racional consiste en restringir el generador de sucesores (Applicable), no en distorsionar la física del problema 
