AI Trader Research Lab — parche V2.3 (no es un proyecto independiente)

ARCHIVOS: copiar backend/prospectivo_v22.py y backend/app/*.py sobre los equivalentes del proyecto, con el proceso detenido y después de hacer copia de seguridad.

CAMBIOS:
- Presupuesto de API por día local America/Managua, incluyendo diagnósticos.
- Si falla maintain() o sigue pendiente el cierre de una posición vencida, no se analizan nuevas entradas en ese ciclo.
- Registrar cada deal con la fecha local real de ejecución.
- Solo BUY/SELL válidos pueden llamar a enter().

NO MODIFICADO: autenticación, conexión, configuración de comisiones y slippage, noticias, estrategia, modelos, base de datos.
NO HABILITAR --demo hasta validar comisiones reales, calendario de noticias actualizado y cierres en cuenta demo.
NO GARANTIZA que el sistema sobreviva apagado del PC, pérdida de internet ni que los stops limiten pérdidas durante gaps.

PRUEBA SEGURA (sin órdenes):
  .\.venv\Scripts\python.exe -m compileall -q .\app .\prospectivo_v22.py
  .\.venv\Scripts\python.exe .\prospectivo_v22.py --status

La validación de velas de M15/H1 se revisó: su comparación con el límite temporal inferior ya era correcta; no se cambió.
