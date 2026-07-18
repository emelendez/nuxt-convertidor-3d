---
name: plan-to-issue-flow
description: Cuando un plan de Claude Code acaba de ser aprobado en este repositorio, crea la issue de GitHub correspondiente (titulo, cuerpo, autoasignacion y labels), y mas tarde, tras implementar y verificar el plan, publica el resumen como comentario y pide confirmacion antes de hacer commit+push referenciando esa issue.
---

Esta skill define el flujo de trazabilidad "plan aprobado -> issue de GitHub"
para el repositorio `emelendez/nuxt-convertidor-3d`. Normalmente se invoca sola:
un hook `PostToolUse` (matcher `ExitPlanMode`, en `.claude/settings.json`) avisa
a Claude en cuanto el usuario aprueba un plan, inyectando una instruccion para
que sigas el Paso 1 de aqui abajo. Los pasos 2 y 3 no los dispara ningun hook
adicional: siguelos tu mismo, por continuidad, dentro de la misma conversacion
en la que implementas y verificas el plan.

Requiere `gh` (GitHub CLI) instalado y autenticado (`gh auth status`). Si no
esta disponible, avisa al usuario y no intentes ejecutar los pasos de GitHub.

## Paso 1 - Crear la issue (justo tras la aprobacion del plan)

1. Localiza el fichero de plan recien aprobado. Su ruta exacta suele estar ya
   en tu contexto de conversacion (el mensaje de sistema de "plan mode" te la
   dio al escribirlo, algo como `~/.claude/plans/<slug>.md`). Si no la
   encuentras en el contexto (p.ej. tras una compactacion), usa Glob sobre
   `~/.claude/plans/*.md` y toma el fichero modificado mas recientemente.
2. Lee el contenido integro del plan.
3. Deriva:
   - **Titulo**: el primer encabezado `#`/`##` del plan, o si no hay, la
     primera frase, recortado a algo conciso (menos de ~70 caracteres).
   - **Cuerpo**: el contenido integro del plan (markdown), tal cual.
4. Ejecuta `gh label list` (o `gh label list --repo emelendez/nuxt-convertidor-3d`
   si no estas en el directorio del repo) y elige, SOLO de las labels que ya
   existen, las que mejor representen el plan (p.ej. `enhancement` para
   funcionalidad nueva, `bug` para una correccion, `documentation` para
   cambios de documentacion). No crees labels nuevas por tu cuenta; si
   ninguna encaja bien, crea la issue sin labels en vez de inventar una.
5. Crea la issue autoasignada a `emelendez`:
   ```
   gh issue create --repo emelendez/nuxt-convertidor-3d \
     --title "<titulo>" --body-file <fichero-temporal-con-el-cuerpo> \
     --assignee emelendez --label "<label1>,<label2>"
   ```
   (usa un fichero temporal para el cuerpo en vez de `--body` para evitar
   problemas de escapado con markdown/comillas/saltos de linea).
6. Del resultado de `gh issue create` (imprime la URL de la issue creada),
   extrae el numero de issue y guardalo para el resto de esta conversacion en
   `.claude/state/<slug-del-plan>.md.json` (crea la carpeta `.claude/state/`
   si no existe) con forma:
   ```json
   { "issue": <numero>, "planFile": "<ruta al .md del plan>", "repo": "emelendez/nuxt-convertidor-3d" }
   ```
   Esto sirve de respaldo por si la conversacion se compacta antes de llegar
   al Paso 2 o 3.
7. Informa brevemente al usuario de que has creado la issue (numero + URL).

## Paso 2 - Comentario de resumen (tras implementar y verificar el plan)

Cuando hayas terminado de implementar el plan Y lo hayas verificado (tests,
comprobacion manual, ejecucion real, etc. segun corresponda a la tarea):

1. Recupera el numero de issue: primero de tu contexto de conversacion: si no
   lo tienes, leelo del fichero `.claude/state/<slug>.md.json` del Paso 1.
2. Redacta un resumen conciso (2-6 lineas) de lo que realmente se hizo y como
   se verifico — no repitas el plan entero, cuenta el resultado.
3. Publicalo como comentario:
   ```
   gh issue comment <numero> --repo emelendez/nuxt-convertidor-3d --body "<resumen>"
   ```

## Paso 3 - Confirmacion antes de hacer push

1. Prepara un mensaje de commit:
   - Titulo: conciso, en modo imperativo, sin punto final.
   - Cuerpo: 1-3 lineas resumiendo el cambio (puede reutilizar el resumen del
     Paso 2).
   - Ultima linea: `Refs #<numero>` (enlaza la issue sin cerrarla
     automaticamente al mergear).
   - **NO incluyas ninguna firma tipo `Co-Authored-By: Claude...`** — esta es
     una excepcion explicita a la convencion habitual de commits de Claude
     Code, valida solo para este flujo.
2. Muestra el mensaje propuesto al usuario y pide confirmacion explicita
   (p.ej. con la pregunta al usuario) antes de hacer `git push`. Si el
   working tree tiene cambios sin commitear relacionados con el plan, puedes
   crear el commit localmente como parte de la propuesta, pero el `git push`
   en si necesita esa confirmacion previa.
3. Si el usuario confirma: `git add` de los ficheros relevantes, `git commit`
   con el mensaje preparado, y `git push`.
4. Si el usuario no confirma: no hagas push. Puedes dejar el commit creado
   localmente si el usuario lo prefiere asi, o no tocar nada mas.