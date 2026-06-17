import re
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Facturación API", version="1.0.0")


def parse_float(value) -> float:
    """Convierte strings numéricos (con comas, puntos, espacios o símbolos de moneda) a float."""
    if value is None or str(value).strip() == "":
        return 0.0

    val_str = str(value).strip()
    val_str = re.sub(r"[^\d.,]", "", val_str)

    if not val_str:
        return 0.0

    if "," in val_str:
        val_str = val_str.replace(".", "").replace(",", ".")

    try:
        return float(val_str)
    except ValueError:
        return 0.0


def to_comma_str(value: float) -> str:
    """Convierte un número a string con coma decimal."""
    if value == 0 or value == 0.0:
        return "0"
    return f"{value:.2f}".replace(".", ",")


@app.post("/api")
async def procesar_comprobante(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="No se recibió un cuerpo JSON válido en la petición")

    if not body:
        raise HTTPException(status_code=400, detail="No se recibió un cuerpo JSON válido en la petición")

    try:
        # 1. CUIT del emisor (solo números)
        cuit_raw = re.sub(r"\D", "", body.get("CUIT del emisor", ""))
        if len(cuit_raw) != 11:
            raise HTTPException(
                status_code=422,
                detail=f"Validación de CUIT fallida. Se esperaban 11 dígitos, se obtuvo: '{cuit_raw}'"
            )
        cuit_emisor = cuit_raw

        # 2. Tipo de comprobante (Mapeo robusto insensible a tildes y mayúsculas)
        tipo_raw = body.get("Tipo de comprobante", "").strip().upper()
        tipo_normalizado = (
            tipo_raw
            .replace("Á", "A")
            .replace("É", "E")
            .replace("Í", "I")
            .replace("Ó", "O")
            .replace("Ú", "U")
        )

        tipo_comprobante = "Factura"
        if "DEBITO" in tipo_normalizado:
            tipo_comprobante = "Nota de débito"
        elif "CREDITO" in tipo_normalizado:
            tipo_comprobante = "Nota de crédito"
        elif "TIQUE" in tipo_normalizado or "TICKET" in tipo_normalizado:
            tipo_comprobante = "Tique factura"

        # 3. Punto de venta y Número de comprobante
        punto_venta = int(parse_float(body.get("Punto de venta", 0)))
        num_comprobante = int(parse_float(body.get("Número de comprobante", 0)))

        # 4. Nombre del emisor
        nombre_emisor = body.get("Nombre del emisor", "").strip()[:30]

        # 5. Alícuotas de IVA
        ivas_obj = body.get("Importes de IVA", {})
        cant_alicuotas = 0
        suma_ivas = 0.0

        if isinstance(ivas_obj, dict):
            for tasa, valor in ivas_obj.items():
                if valor and str(valor).strip() != "":
                    val_float = parse_float(valor)
                    if val_float > 0:
                        cant_alicuotas += 1
                        suma_ivas += val_float

        if suma_ivas == 0.0:
            suma_ivas = parse_float(body.get("Importe total de IVA del comprobante", 0))

        # 6. Parseo numérico defensivo de todos los componentes
        neto_gravado      = parse_float(body.get("Netos gravados", 0))
        no_gravado        = parse_float(body.get("Importe No gravado", 0))
        exento            = parse_float(body.get("Importe Exento", 0))
        percepcion_iva    = parse_float(body.get("Importe Percepción de IVA", 0))
        percepcion_iigg   = parse_float(body.get("Importe Percepción de impuesto a las ganancias", 0))
        percepcion_iibb   = parse_float(body.get("Importe Percepción Ingresos Brutos", 0))
        imp_municipales   = parse_float(body.get("Importe Impuestos municipales", 0))
        imp_internos      = parse_float(body.get("Importe Impuestos Internos u otros tributos específicos sueltos", 0))
        otros_trib_globales = parse_float(body.get("Importe de otros tributos globales", 0))
        total_comprobante = parse_float(body.get("Importe total del comprobante", 0))

        # 7. Control numérico (tolerancia ±1 peso)
        # Se usa solo uno de los dos tributos: otros_trib_globales tiene prioridad;
        # si vale 0, se usa imp_internos.
        tributo_efectivo = otros_trib_globales if otros_trib_globales > 0 else imp_internos

        sumatoria_componentes = (
            neto_gravado
            + suma_ivas
            + no_gravado
            + exento
            + percepcion_iva
            + percepcion_iigg
            + percepcion_iibb
            + imp_municipales
            + tributo_efectivo
        )

        if abs(total_comprobante - sumatoria_componentes) > 1.0:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Error de cuadre matemático",
                    "total_comprobante": total_comprobante,
                    "suma_calculada": sumatoria_componentes,
                }
            )

        # 8. Construcción del JSON de salida
        resultado = {
            "Fecha de emisión": body.get("Fecha de emisión", "").strip(),
            "Tipo de comprobante": tipo_comprobante,
            "Punto de venta": punto_venta,
            "Número de comprobante": num_comprobante,
            "CUIT del emisor": cuit_emisor,
            "Nombre del emisor": nombre_emisor,
            "Importe total del comprobante": to_comma_str(total_comprobante),
            "Importe No gravado.": to_comma_str(no_gravado),
            "Importe Exento.": to_comma_str(exento),
            "Importe Percepción de IVA.": to_comma_str(percepcion_iva),
            "Importe Percepción de impuesto a las ganancias": to_comma_str(percepcion_iigg),
            "Importe Percepción Ingresos Brutos.": to_comma_str(percepcion_iibb),
            "Importe Impuestos municipales.": to_comma_str(imp_municipales),
            "Importe Impuestos Internos u otros tributos específicos sueltos.": to_comma_str(imp_internos),
            "Cantidad de alícuotas de IVA presentes": cant_alicuotas,
            "Importe total de IVA del comprobante.": to_comma_str(suma_ivas),
            "Importe de otros tributos globales.": to_comma_str(otros_trib_globales),
        }

        return JSONResponse(content=resultado, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Internal Server Error", "details": str(e)})
