"""
aml_individual.py
─────────────────────────────────────────────────────────────────────────────
Módulo de Análisis AML Individual para WatchTower.
Recibe filas de las queries OUT e IN, ejecuta el pipeline completo de
análisis y genera el Excel de 12 hojas con formato Global66.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import io
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("aml_individual")

# ── Paleta de colores Global66 ────────────────────────────────────────────
DARK_NAVY    = '#0D1B2A'
NAVY         = '#1B3A6B'
LIGHT_BLUE   = '#DBEAFE'
LIGHT_GRAY   = '#F3F4F6'
WHITE        = '#FFFFFF'
BORDER_COL   = '#D1D5DB'
TEXT_DARK    = '#1F2937'
CRITICO_BG   = '#DC2626'
ALTO_BG      = '#EA580C'
MEDIO_BG     = '#FEF9C3'
BAJO_BG      = '#DCFCE7'
FLAG_YES_BG  = '#FEE2E2'
FLAG_NO_BG   = '#DCFCE7'
PURPLE       = '#7C3AED'
LIGHT_PURPLE = '#EDE9FE'

HIGH_RISK_COUNTRIES = {
    'Venezuela', 'Myanmar', 'Corea del Norte', 'Iran', 'Irán', 'Rusia', 'Cuba', 'Siria',
    'Haití', 'Haiti', 'Pakistán', 'Pakistan', 'Mali', 'Burkina Faso', 'Camerún', 'Camerun',
    'Congo', 'Mozambique', 'Tanzania', 'Nicaragua', 'Panamá', 'Panama', 'Yemen',
    'Afganistán', 'Afghanistan', 'North Korea', 'Syria', 'Russia',
}

# ── Pesos de los flags ────────────────────────────────────────────────────
FLAG_WEIGHTS = {
    'flag_structuring':   3,
    'flag_velocidad':     2,
    'flag_fanout':        2,
    'flag_monto_alto':    2,
    'flag_pais_riesgo':   3,
    'flag_redondos':      1,
    'flag_devolucion':    2,
    'flag_concentracion': 1,
    'flag_crecimiento':   2,
    'flag_diversif':      1,
}

FLAG_LABELS = {
    'flag_structuring':   'F1 Estructuración',
    'flag_velocidad':     'F2 Velocidad',
    'flag_fanout':        'F3 Fan-Out',
    'flag_monto_alto':    'F4 Monto Alto',
    'flag_pais_riesgo':   'F5 País Riesgo',
    'flag_redondos':      'F6 Montos Redondos',
    'flag_devolucion':    'F7 Devolución',
    'flag_concentracion': 'F8 Concentración',
    'flag_crecimiento':   'F9 Crecimiento',
    'flag_diversif':      'F10 Diversificación',
}


# ── Utilidades ────────────────────────────────────────────────────────────

def _to_float(val) -> float:
    """Convierte a float manejando None, strings con comas, Decimal. Retorna 0.0 si falla."""
    if val is None:
        return 0.0
    if isinstance(val, float):
        return val
    if isinstance(val, int):
        return float(val)
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (InvalidOperation, ValueError):
            return 0.0
    if isinstance(val, str):
        cleaned = val.replace(',', '.').strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(val) -> dt.datetime | None:
    """Parsea un valor a datetime. Acepta datetime, date, strings ISO."""
    if val is None:
        return None
    if isinstance(val, dt.datetime):
        return val
    if isinstance(val, dt.date):
        return dt.datetime(val.year, val.month, val.day)
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        for fmt in (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%d',
        ):
            try:
                return dt.datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


# ── Pipeline principal ────────────────────────────────────────────────────

def _prepare_df(rows_out: list[dict], rows_in: list[dict]) -> tuple[list[dict], dict]:
    """Combina las dos listas, normaliza campos y filtra solo txs exitosas.
    Retorna (rows_filtradas, total_por_cliente) donde total_por_cliente
    es el conteo de TODAS las filas (IN+OUT) antes del filtro de status."""

    # Contar TODAS las filas antes de filtrar, por customer_id
    total_por_cliente: dict = defaultdict(int)
    for row in rows_out:
        cid = row.get('customer_id')
        if cid is not None:
            total_por_cliente[cid] += 1
    for row in rows_in:
        cid = row.get('customer_id')
        if cid is not None:
            total_por_cliente[cid] += 1

    result = []

    for row in rows_out:
        r = dict(row)
        r['flujo'] = 'OUT'
        status = (r.get('tx_status') or '').upper()
        if status not in ('TRANSFERENCIA_EXITOSA',):
            continue
        r['origin_amount_usd'] = _to_float(r.get('origin_amount_usd'))
        parsed = _parse_date(r.get('start_date'))
        if parsed:
            r['_start_dt'] = parsed
            r['date_only'] = parsed.date()
            r['hour_of_day'] = parsed.hour
            r['month_period'] = parsed.strftime('%Y-%m')
        else:
            r['_start_dt'] = None
            r['date_only'] = None
            r['hour_of_day'] = None
            r['month_period'] = None
        result.append(r)

    for row in rows_in:
        r = dict(row)
        r['flujo'] = 'IN'
        status = (r.get('tx_status') or '').upper()
        if status not in ('PAID',):
            continue
        r['origin_amount_usd'] = _to_float(r.get('origin_amount_usd'))
        parsed = _parse_date(r.get('start_date'))
        if parsed:
            r['_start_dt'] = parsed
            r['date_only'] = parsed.date()
            r['hour_of_day'] = parsed.hour
            r['month_period'] = parsed.strftime('%Y-%m')
        else:
            r['_start_dt'] = None
            r['date_only'] = None
            r['hour_of_day'] = None
            r['month_period'] = None
        result.append(r)

    return result, dict(total_por_cliente)


def _calc_flags(rows: list[dict], total_por_cliente: dict) -> dict:
    """Agrupa por customer_id y calcula los 10 flags + métricas de soporte."""
    by_customer: dict = defaultdict(list)
    for r in rows:
        cid = r.get('customer_id')
        if cid is not None:
            by_customer[cid].append(r)

    flags_map = {}
    now = dt.datetime.utcnow()
    cutoff_recent = now - dt.timedelta(days=30)
    cutoff_prev = now - dt.timedelta(days=60)

    for cid, txs in by_customer.items():
        # Información de cliente
        sample = txs[0]
        customer_name = f"{sample.get('customer_name', '') or ''} {sample.get('customer_last_name', '') or ''}".strip()
        customer_email = sample.get('customer_email', '') or ''

        # customer_identification: primer valor no nulo en las txs del cliente
        customer_identification = None
        for r in txs:
            ident = r.get('customer_identification')
            if ident:
                customer_identification = ident
                break

        # Métricas generales
        n_txs_exitosas = len(txs)
        n_txs_total = total_por_cliente.get(cid, n_txs_exitosas)
        vol_total = sum(_to_float(r.get('origin_amount_usd')) for r in txs)
        ticket_prom = vol_total / n_txs_exitosas if n_txs_exitosas > 0 else 0.0

        # max_tx_usd
        max_tx_usd = max((_to_float(r.get('origin_amount_usd')) for r in txs), default=0.0)

        # Txs OUT solamente
        txs_out = [r for r in txs if r.get('flujo') == 'OUT']
        n_out = len(txs_out)

        # F1: Estructuración — 2+ txs OUT con monto entre 8000 y 9999.99 USD
        struct_txs = [r for r in txs_out if 8000.0 <= _to_float(r.get('origin_amount_usd')) <= 9999.99]
        flag_structuring = 1 if len(struct_txs) >= 2 else 0
        n_structuring = len(struct_txs)

        # F2: Velocidad — 5+ txs en el mismo date_only
        # (umbral subido de 3→5: en Global66 B2C/B2B, 3-4 txs/día es rutinario)
        dates_counter: dict = defaultdict(int)
        for r in txs:
            d = r.get('date_only')
            if d is not None:
                dates_counter[d] += 1
        max_txs_per_day = max(dates_counter.values()) if dates_counter else 0
        flag_velocidad = 1 if max_txs_per_day >= 5 else 0

        # F3: Fan-out — 5+ beneficiary_id distintos (solo OUT)
        bene_ids_out = {r.get('beneficiary_id') for r in txs_out if r.get('beneficiary_id')}
        n_beneficiarios = len(bene_ids_out)
        flag_fanout = 1 if n_beneficiarios >= 5 else 0

        # F4: Monto alto — 2+ txs con origin_amount_usd >= 10000
        # (umbral subido de 1→2 txs: una sola transferencia de $10K es normal en remesas B2B;
        #  la repetición indica patrón sistemático de montos sobre umbral de reporte)
        monto_alto_txs = [r for r in txs if _to_float(r.get('origin_amount_usd')) >= 10000.0]
        n_txs_monto_alto = len(monto_alto_txs)
        flag_monto_alto = 1 if n_txs_monto_alto >= 2 else 0

        # F5: País riesgo — destiny_country en HIGH_RISK_COUNTRIES
        paises_dest = {r.get('destiny_country') for r in txs_out if r.get('destiny_country')}
        paises_riesgo_encontrados = paises_dest & HIGH_RISK_COUNTRIES
        flag_pais_riesgo = 1 if paises_riesgo_encontrados else 0

        # F6: Montos redondos — >70% txs son múltiplos de 1000/5000/10000/50000/100000
        REDONDOS = (100000, 50000, 10000, 5000, 1000)
        def es_redondo(amt: float) -> bool:
            for r_val in REDONDOS:
                if amt > 0 and abs(amt % r_val) < 0.01:
                    return True
            return False

        if n_txs_exitosas >= 3:
            n_redondos = sum(1 for r in txs if es_redondo(_to_float(r.get('origin_amount_usd'))))
            pct_redondos = n_redondos / n_txs_exitosas
            flag_redondos = 1 if pct_redondos > 0.70 else 0
        else:
            flag_redondos = 0
            pct_redondos = 0.0

        # F7: Devolución — siempre 0
        flag_devolucion = 0
        n_devuelto = 0
        tasa_devolucion_pct = 0.0

        # F8: Concentración — 1 beneficiario recibe >80% del volumen (con 3+ beneficiarios distintos)
        max_concentracion_pct = 0.0
        if n_out >= 1 and n_beneficiarios >= 3:
            vol_by_bene: dict = defaultdict(float)
            for r in txs_out:
                bid = r.get('beneficiary_id') or '__none__'
                vol_by_bene[bid] += _to_float(r.get('origin_amount_usd'))
            vol_total_out = sum(vol_by_bene.values())
            if vol_total_out > 0:
                max_bene_vol = max(vol_by_bene.values())
                max_concentracion_pct = round(max_bene_vol / vol_total_out * 100, 2)
                flag_concentracion = 1 if (max_bene_vol / vol_total_out) > 0.80 else 0
            else:
                flag_concentracion = 0
        else:
            flag_concentracion = 0

        # F9: Crecimiento — vol últimos 30d >= 3x los 30d previos, con vol_reciente > 5000
        txs_recientes = [r for r in txs if r.get('_start_dt') and r['_start_dt'] >= cutoff_recent]
        txs_previas = [r for r in txs if r.get('_start_dt') and cutoff_prev <= r['_start_dt'] < cutoff_recent]
        vol_reciente = sum(_to_float(r.get('origin_amount_usd')) for r in txs_recientes)
        vol_previo = sum(_to_float(r.get('origin_amount_usd')) for r in txs_previas)
        ratio_crecimiento = round(vol_reciente / vol_previo, 4) if vol_previo > 0 else 0.0
        if vol_previo > 0 and vol_reciente > 5000.0:
            flag_crecimiento = 1 if (vol_reciente / vol_previo) >= 3.0 else 0
        else:
            flag_crecimiento = 0

        # F10: Diversificación — envíos a 4+ países destino distintos
        n_paises_destino = len({r.get('destiny_country') for r in txs_out if r.get('destiny_country')})
        flag_diversif = 1 if n_paises_destino >= 4 else 0

        # Risk score
        risk_score = (
            flag_structuring   * FLAG_WEIGHTS['flag_structuring']   +
            flag_velocidad     * FLAG_WEIGHTS['flag_velocidad']      +
            flag_fanout        * FLAG_WEIGHTS['flag_fanout']         +
            flag_monto_alto    * FLAG_WEIGHTS['flag_monto_alto']     +
            flag_pais_riesgo   * FLAG_WEIGHTS['flag_pais_riesgo']    +
            flag_redondos      * FLAG_WEIGHTS['flag_redondos']       +
            flag_devolucion    * FLAG_WEIGHTS['flag_devolucion']     +
            flag_concentracion * FLAG_WEIGHTS['flag_concentracion']  +
            flag_crecimiento   * FLAG_WEIGHTS['flag_crecimiento']    +
            flag_diversif      * FLAG_WEIGHTS['flag_diversif']
        )

        # Umbrales de clasificación de riesgo (score máximo alcanzable: 17, F7=0)
        # BAJO     0-2:  comportamiento rutinario de remesas, sin patrones sospechosos
        # MEDIO    3-5:  1 indicador significativo activo (ej. estructuración o país riesgo)
        # ALTO     6-9:  2+ indicadores combinados (patrones más sólidos de sospecha)
        # CRÍTICO  ≥10:  múltiples banderas graves simultáneas
        if risk_score >= 10:
            nivel_riesgo = 'CRÍTICO'
        elif risk_score >= 6:
            nivel_riesgo = 'ALTO'
        elif risk_score >= 3:
            nivel_riesgo = 'MEDIO'
        else:
            nivel_riesgo = 'BAJO'

        flags_map[cid] = {
            'customer_id':            cid,
            'customer_name':          customer_name,
            'customer_email':         customer_email,
            'customer_identification': customer_identification,
            'n_txs_exitosas':         n_txs_exitosas,
            'n_txs_total':            n_txs_total,
            'n_out':                  n_out,
            'vol_total_usd':          round(vol_total, 2),
            'max_tx_usd':             round(max_tx_usd, 2),
            'ticket_promedio_usd':    round(ticket_prom, 2),
            'n_beneficiarios':        n_beneficiarios,
            'flag_structuring':       flag_structuring,
            'flag_velocidad':         flag_velocidad,
            'flag_fanout':            flag_fanout,
            'flag_monto_alto':        flag_monto_alto,
            'flag_pais_riesgo':       flag_pais_riesgo,
            'flag_redondos':          flag_redondos,
            'flag_devolucion':        flag_devolucion,
            'flag_concentracion':     flag_concentracion,
            'flag_crecimiento':       flag_crecimiento,
            'flag_diversif':          flag_diversif,
            'risk_score':             risk_score,
            'nivel_riesgo':           nivel_riesgo,
            # métricas de soporte
            'n_structuring_txs':      n_structuring,
            'max_txs_per_day':        max_txs_per_day,
            'n_txs_monto_alto':       n_txs_monto_alto,
            'pct_redondos':           round(pct_redondos, 3),
            'paises_riesgo':          ', '.join(sorted(paises_riesgo_encontrados)),
            'n_paises_destino':       n_paises_destino,
            'vol_reciente_30d':       round(vol_reciente, 2),
            'vol_previo_30d':         round(vol_previo, 2),
            'max_concentracion_pct':  max_concentracion_pct if flag_concentracion else 0.0,
            'ratio_crecimiento':      ratio_crecimiento,
            'n_devuelto':             n_devuelto,
            'tasa_devolucion_pct':    tasa_devolucion_pct,
        }

    return flags_map


def _calc_corredores(rows: list[dict]) -> list[dict]:
    """Agrupa txs OUT por (origin_country, destiny_country) y calcula métricas de corredor."""
    txs_out = [r for r in rows if r.get('flujo') == 'OUT']

    by_corredor: dict = defaultdict(lambda: {
        'total_txs': 0,
        'clientes': set(),
        'beneficiarios': set(),
        'total_usd': 0.0,
    })

    for r in txs_out:
        origin = r.get('origin_country') or r.get('country_origin') or 'DESCONOCIDO'
        destiny = r.get('destiny_country') or 'DESCONOCIDO'
        key = (origin, destiny)
        bucket = by_corredor[key]
        bucket['total_txs'] += 1
        cid = r.get('customer_id')
        if cid:
            bucket['clientes'].add(cid)
        bene_ident = r.get('beneficiary_identification')
        if bene_ident:
            bucket['beneficiarios'].add(bene_ident)
        bucket['total_usd'] += _to_float(r.get('origin_amount_usd'))

    result = []
    for (origin, destiny), data in by_corredor.items():
        total_usd = round(data['total_usd'], 2)
        total_txs = data['total_txs']
        promedio_usd = round(total_usd / total_txs, 2) if total_txs > 0 else 0.0
        result.append({
            'origin_country':      origin,
            'destiny_country':     destiny,
            'total_txs':           total_txs,
            'clientes_unicos':     len(data['clientes']),
            'beneficiarios_unicos': len(data['beneficiarios']),
            'total_usd':           total_usd,
            'promedio_usd':        promedio_usd,
            'es_pais_riesgo':      destiny in HIGH_RISK_COUNTRIES,
        })

    result.sort(key=lambda x: x['total_usd'], reverse=True)
    return result


def _calc_fanin(rows: list[dict]) -> list[dict]:
    """Agrupa por beneficiary_identification, calcula métricas de fan-in.
    Retorna TODOS los beneficiarios con identificación no nula (umbral >= 1)."""
    by_bene_id: dict = defaultdict(lambda: {
        'customers': set(),
        'bene_ids': set(),
        'cuentas': set(),
        'txs': 0,
        'total_usd': 0.0,
        'sample': None,
    })

    for r in rows:
        bene_ident = r.get('beneficiary_identification')
        if not bene_ident:
            continue
        bucket = by_bene_id[bene_ident]
        cid = r.get('customer_id')
        if cid:
            bucket['customers'].add(cid)
        bid = r.get('beneficiary_id')
        if bid:
            bucket['bene_ids'].add(bid)
        acct = r.get('beneficiary_account_number')
        if acct:
            bucket['cuentas'].add(acct)
        bucket['txs'] += 1
        bucket['total_usd'] += _to_float(r.get('origin_amount_usd'))
        if bucket['sample'] is None:
            bucket['sample'] = r

    result = []
    for bene_ident, data in by_bene_id.items():
        sample = data['sample'] or {}
        result.append({
            'beneficiary_identification':      bene_ident,
            'beneficiary_identification_type': sample.get('beneficiary_identification_type', ''),
            'beneficiary_name':    sample.get('beneficiary_name', ''),
            'beneficiary_last_name': sample.get('beneficiary_last_name', ''),
            'beneficiary_country_code': sample.get('beneficiary_country_code', ''),
            'clientes_unicos':     len(data['customers']),
            'bene_ids_distintos':  len(data['bene_ids']),
            'cuentas_distintas':   len(data['cuentas']),
            'total_txs':           data['txs'],
            'total_usd':           round(data['total_usd'], 2),
        })

    result.sort(key=lambda x: x['clientes_unicos'], reverse=True)
    return result


def _calc_horario(rows: list[dict]) -> list[dict]:
    """Agrupa por hour_of_day, cuenta txns y suma vol_usd."""
    by_hour: dict = defaultdict(lambda: {'txns': 0, 'vol_usd': 0.0})
    for r in rows:
        h = r.get('hour_of_day')
        if h is None:
            continue
        by_hour[h]['txns'] += 1
        by_hour[h]['vol_usd'] += _to_float(r.get('origin_amount_usd'))

    def franja(h: int) -> str:
        if 0 <= h <= 5:
            return 'MADRUGADA'
        elif 6 <= h <= 9:
            return 'MAÑANA'
        elif 10 <= h <= 18:
            return 'HORARIO NORMAL'
        else:
            return 'NOCHE'

    result = []
    for h in range(24):
        d = by_hour[h]
        result.append({
            'hora':     h,
            'franja':   franja(h),
            'txns':     d['txns'],
            'vol_usd':  round(d['vol_usd'], 2),
        })
    return result


def _calc_metodos(rows: list[dict]) -> list[dict]:
    """Agrupa por payment_method."""
    by_method: dict = defaultdict(lambda: {'txns': 0, 'vol_usd': 0.0, 'customers': set()})
    for r in rows:
        m = r.get('payment_method') or 'SIN_METODO'
        by_method[m]['txns'] += 1
        by_method[m]['vol_usd'] += _to_float(r.get('origin_amount_usd'))
        cid = r.get('customer_id')
        if cid:
            by_method[m]['customers'].add(cid)

    result = [
        {
            'payment_method':  method,
            'txns':            data['txns'],
            'vol_usd':         round(data['vol_usd'], 2),
            'clientes_unicos': len(data['customers']),
        }
        for method, data in by_method.items()
    ]
    result.sort(key=lambda x: x['vol_usd'], reverse=True)
    return result


def _calc_paises(rows: list[dict]) -> list[dict]:
    """Agrupa por destiny_country (solo OUT)."""
    txs_out = [r for r in rows if r.get('flujo') == 'OUT']
    by_pais: dict = defaultdict(lambda: {'txns': 0, 'vol_usd': 0.0, 'customers': set()})
    for r in txs_out:
        p = r.get('destiny_country') or 'DESCONOCIDO'
        by_pais[p]['txns'] += 1
        by_pais[p]['vol_usd'] += _to_float(r.get('origin_amount_usd'))
        cid = r.get('customer_id')
        if cid:
            by_pais[p]['customers'].add(cid)

    result = [
        {
            'destiny_country':  pais,
            'txns':             data['txns'],
            'vol_usd':          round(data['vol_usd'], 2),
            'clientes_unicos':  len(data['customers']),
            'es_pais_riesgo':   pais in HIGH_RISK_COUNTRIES,
        }
        for pais, data in by_pais.items()
    ]
    result.sort(key=lambda x: x['vol_usd'], reverse=True)
    return result


def _calc_evolucion(rows: list[dict]) -> list[dict]:
    """Agrupa por month_period con desglose IN/OUT y métricas ampliadas."""
    by_mes: dict = defaultdict(lambda: {
        'txns': 0,
        'vol_usd': 0.0,
        'txns_out': 0,
        'txns_in': 0,
        'vol_out': 0.0,
        'vol_in': 0.0,
        'clientes': set(),
        'benef_unicos': set(),
    })
    for r in rows:
        m = r.get('month_period')
        if not m:
            continue
        bucket = by_mes[m]
        bucket['txns'] += 1
        amt = _to_float(r.get('origin_amount_usd'))
        bucket['vol_usd'] += amt
        flujo = r.get('flujo')
        if flujo == 'OUT':
            bucket['txns_out'] += 1
            bucket['vol_out'] += amt
            bene_ident = r.get('beneficiary_identification')
            if bene_ident:
                bucket['benef_unicos'].add(bene_ident)
        elif flujo == 'IN':
            bucket['txns_in'] += 1
            bucket['vol_in'] += amt
        cid = r.get('customer_id')
        if cid:
            bucket['clientes'].add(cid)

    result = [
        {
            'mes':             mes,
            'txns':            data['txns'],
            'vol_usd':         round(data['vol_usd'], 2),
            'txns_out':        data['txns_out'],
            'txns_in':         data['txns_in'],
            'vol_out':         round(data['vol_out'], 2),
            'vol_in':          round(data['vol_in'], 2),
            'clientes_activos': len(data['clientes']),
            'benef_unicos':    len(data['benef_unicos']),
        }
        for mes, data in by_mes.items()
    ]
    result.sort(key=lambda x: x['mes'])
    return result


def _hallazgos(
    rows: list[dict],
    flags_map: dict,
    fanin_rows: list[dict],
    metodos: list[dict],
    paises: list[dict],
) -> list[dict]:
    """Genera lista de hasta 6 hallazgos críticos."""
    hallazgos = []
    num = 1

    # 1. Clientes con flag_pais_riesgo
    clientes_pais_riesgo = [f for f in flags_map.values() if f['flag_pais_riesgo']]
    if clientes_pais_riesgo:
        paises_riesgo_set = set()
        for f in clientes_pais_riesgo:
            if f.get('paises_riesgo'):
                paises_riesgo_set.update(f['paises_riesgo'].split(', '))
        hallazgos.append({
            'num':        num,
            'hallazgo':   'Transacciones a Países de Riesgo',
            'descripcion': (
                f"{len(clientes_pais_riesgo)} cliente(s) registran envíos a jurisdicciones "
                f"de alto riesgo: {', '.join(sorted(paises_riesgo_set))}. "
                "Requiere revisión inmediata y potencial reporte ROS."
            ),
        })
        num += 1

    # 2. Actividad nocturna (00-05h) > 15% del total
    total_txs = len(rows)
    if total_txs > 0:
        madrugada_txs = sum(
            1 for r in rows if r.get('hour_of_day') is not None and 0 <= r['hour_of_day'] <= 5
        )
        pct_madrugada = madrugada_txs / total_txs
        if pct_madrugada > 0.15:
            hallazgos.append({
                'num':        num,
                'hallazgo':   'Actividad Inusual en Horario Nocturno',
                'descripcion': (
                    f"{madrugada_txs} transacciones ({pct_madrugada:.1%}) ocurrieron entre 00:00 y 05:59h. "
                    "La actividad en madrugada supera el umbral del 15% — indicador de posible automatización "
                    "o uso de la plataforma en horario atípico."
                ),
            })
            num += 1

    # 3. Top 3 beneficiarios por clientes_unicos (con >=3 clientes)
    top_fanin = [b for b in fanin_rows if b['clientes_unicos'] >= 3][:3]
    if top_fanin:
        desc_parts = []
        for b in top_fanin:
            nombre = f"{b.get('beneficiary_name', '')} {b.get('beneficiary_last_name', '')}".strip() or 'Sin nombre'
            desc_parts.append(
                f"{nombre} (ID: {b['beneficiary_identification']}) — "
                f"{b['clientes_unicos']} clientes, {b['total_txs']} txs, "
                f"USD {b['total_usd']:,.2f}"
            )
        hallazgos.append({
            'num':        num,
            'hallazgo':   'Beneficiarios con Fan-In Elevado',
            'descripcion': (
                "Se detectaron beneficiarios que reciben fondos de múltiples clientes: "
                + " | ".join(desc_parts)
            ),
        })
        num += 1

    # 4. Si algún payment_method > 80% de txns
    if metodos and total_txs > 0:
        total_method_txns = sum(m['txns'] for m in metodos)
        for m in metodos:
            if total_method_txns > 0 and (m['txns'] / total_method_txns) > 0.80:
                hallazgos.append({
                    'num':        num,
                    'hallazgo':   f"Concentración en Método de Pago: {m['payment_method']}",
                    'descripcion': (
                        f"El método '{m['payment_method']}' concentra el "
                        f"{m['txns']/total_method_txns:.1%} de todas las transacciones "
                        f"({m['txns']} txs, USD {m['vol_usd']:,.2f}). "
                        "Revisar si corresponde al perfil esperado del cliente."
                    ),
                })
                num += 1
                break

    # 5. Clientes CRÍTICO
    clientes_criticos = [f for f in flags_map.values() if f['nivel_riesgo'] == 'CRÍTICO']
    if clientes_criticos:
        nombres = ', '.join(
            f.get('customer_name') or f"ID:{f['customer_id']}"
            for f in clientes_criticos[:5]
        )
        hallazgos.append({
            'num':        num,
            'hallazgo':   'Clientes con Score de Riesgo CRÍTICO',
            'descripcion': (
                f"{len(clientes_criticos)} cliente(s) alcanzaron nivel de riesgo CRÍTICO "
                f"(score ≥ 12): {nombres}. "
                "Estos perfiles requieren revisión exhaustiva y documentación de debida diligencia reforzada."
            ),
        })
        num += 1

    # 6. Fan-in >= 4 clientes
    fanin_alto = [b for b in fanin_rows if b['clientes_unicos'] >= 4]
    if fanin_alto and num <= 6:
        hallazgos.append({
            'num':        num,
            'hallazgo':   'Red de Beneficiarios de Alto Fan-In',
            'descripcion': (
                f"Se identificaron {len(fanin_alto)} beneficiario(s) que reciben fondos de "
                f"4 o más clientes distintos. El beneficiario con mayor fan-in recibe de "
                f"{fanin_alto[0]['clientes_unicos']} clientes diferentes "
                f"(ID: {fanin_alto[0]['beneficiary_identification']}). "
                "Este patrón puede indicar estructuración coordinada o layering."
            ),
        })
        num += 1

    return hallazgos[:6]


# ── Constructor del Excel ─────────────────────────────────────────────────

def _hex_to_xlsxwriter(color: str) -> str:
    """Remueve el # para xlsxwriter."""
    return color.lstrip('#')


def build_aml_excel(
    rows_out: list[dict],
    rows_in: list[dict],
    customer_ids: list,
    rows_cashcall_in: list[dict] | None = None,
) -> bytes:
    """Función principal. Construye el Excel AML.

    El motor de scoring/flags (hojas 1-12) opera EXCLUSIVAMENTE sobre rows_out +
    rows_in — remesas (transaction.transaction) y CCA pay-in vía wallet_deposit.
    Es el mismo motor y las mismas 2 fuentes de siempre; no se tocan.

    rows_cashcall_in (treasury.cash_call, type='CR') es una fuente aparte, con
    campos propios que no corresponden 1:1 con las anteriores. Se muestra en su
    propia hoja, sin mezclarse con el cálculo de flags.
    """
    import xlsxwriter

    # ── Preparación de datos
    rows, total_por_cliente = _prepare_df(rows_out, rows_in)
    flags_map = _calc_flags(rows, total_por_cliente)
    corredores = _calc_corredores(rows)
    fanin_rows = _calc_fanin(rows)
    horario = _calc_horario(rows)
    metodos = _calc_metodos(rows)
    paises = _calc_paises(rows)
    evolucion = _calc_evolucion(rows)
    hallazgos = _hallazgos(rows, flags_map, fanin_rows, metodos, paises)

    # Índice txs por cliente para hoja 3 (fichas)
    txs_by_customer: dict = defaultdict(list)
    for r in rows:
        cid = r.get('customer_id')
        if cid is not None:
            txs_by_customer[cid].append(r)

    # Métricas globales.
    # IMPORTANTE: cash_call NO entra al motor de scoring/flags (rows/flags_map
    # siguen siendo solo remesas+CCA wallet, sin tocar). Pero SÍ se suma a los
    # KPIs generales de arriba — si no, un cliente que solo usa cash_call
    # aparece con "Total Transacciones: 0" aunque tenga actividad real.
    cashcall_rows = rows_cashcall_in or []
    n_cashcall = len(cashcall_rows)
    vol_cashcall_usd = sum(_to_float(r.get('origin_amount_usd')) for r in cashcall_rows)

    total_txs_all = len(rows_out) + len(rows_in) + n_cashcall
    total_txs_exitosas = len(rows) + n_cashcall  # cash_call ya viene filtrado a status='PAID'
    n_clientes = len({
        *flags_map.keys(),
        *(r.get('customer_id') for r in cashcall_rows if r.get('customer_id') is not None),
    }) or len(set(customer_ids))
    vol_total_usd = sum(f['vol_total_usd'] for f in flags_map.values()) + vol_cashcall_usd
    ticket_prom = vol_total_usd / total_txs_exitosas if total_txs_exitosas > 0 else 0.0
    bene_unicos_total = len({r.get('beneficiary_id') for r in rows if r.get('beneficiary_id')})
    bene_multi = sum(1 for b in fanin_rows if b['bene_ids_distintos'] > 1)
    txs_pais_riesgo = sum(1 for r in rows if r.get('destiny_country') in HIGH_RISK_COUNTRIES)

    # Distribución por nivel
    by_nivel: dict = {'CRÍTICO': {'clientes': 0, 'vol': 0.0},
                      'ALTO':    {'clientes': 0, 'vol': 0.0},
                      'MEDIO':   {'clientes': 0, 'vol': 0.0},
                      'BAJO':    {'clientes': 0, 'vol': 0.0}}
    for f in flags_map.values():
        nivel = f['nivel_riesgo']
        by_nivel[nivel]['clientes'] += 1
        by_nivel[nivel]['vol'] += f['vol_total_usd']
    total_clientes_con_data = sum(v['clientes'] for v in by_nivel.values())
    total_vol_con_data = sum(v['vol'] for v in by_nivel.values())

    # ── Crear workbook
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {'in_memory': True, 'default_date_format': 'yyyy-mm-dd hh:mm:ss'})

    # ── Formatos comunes ─────────────────────────────────────────────────

    def _fmt(**kwargs):
        return wb.add_format(kwargs)

    # Título principal
    fmt_titulo = _fmt(
        bold=True, font_size=14, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(DARK_NAVY),
        align='center', valign='vcenter',
    )
    # Subtítulo (azul oscuro)
    fmt_subtitulo = _fmt(
        bold=True, font_size=10, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(NAVY),
        align='left', valign='vcenter',
    )
    # Encabezado sección
    fmt_seccion = _fmt(
        bold=True, font_size=10, font_color=_hex_to_xlsxwriter(NAVY),
        bg_color=_hex_to_xlsxwriter(LIGHT_BLUE),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    # Header de tabla
    fmt_header = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(NAVY),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        text_wrap=True,
    )
    # Dato normal
    fmt_dato = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_dato_center = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_dato_num = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='right', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        num_format='#,##0.00',
    )
    fmt_dato_int = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='right', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        num_format='#,##0',
    )
    fmt_dato_gris = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(LIGHT_GRAY),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_dato_gris_num = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(LIGHT_GRAY),
        align='right', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        num_format='#,##0.00',
    )
    # Nivel de riesgo
    fmt_critico = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_alto = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(ALTO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_medio = _fmt(
        bold=True, font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(MEDIO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_bajo = _fmt(
        bold=True, font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(BAJO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    # Flags
    fmt_flag_yes = _fmt(
        bold=True, font_size=9, font_color='C00000',
        bg_color=_hex_to_xlsxwriter(FLAG_YES_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_flag_no = _fmt(
        font_size=9, font_color='6B7280',
        bg_color=_hex_to_xlsxwriter(FLAG_NO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    # Hallazgos críticos
    fmt_hallazgo_header = _fmt(
        bold=True, font_size=10, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='left', valign='vcenter',
    )
    fmt_hallazgo_num = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(ALTO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_hallazgo_titulo = _fmt(
        bold=True, font_size=9, font_color=_hex_to_xlsxwriter(DARK_NAVY),
        bg_color=_hex_to_xlsxwriter(LIGHT_BLUE),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_hallazgo_desc = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        text_wrap=True,
    )
    # Purple (multi-registro)
    fmt_purple = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(PURPLE),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    # Alerta colors
    fmt_alerta_struct = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color='FEF9C3',
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_alerta_alto = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(FLAG_YES_BG),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_alerta_pais = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color='FFEDD5',
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    # Hoja 3 fichas — cabecera cliente
    fmt_ficha_critico = _fmt(
        bold=True, font_size=11, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_alto = _fmt(
        bold=True, font_size=11, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(ALTO_BG),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_label = _fmt(
        bold=True, font_size=9, font_color=_hex_to_xlsxwriter(NAVY),
        bg_color=_hex_to_xlsxwriter(LIGHT_BLUE),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_valor = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=WHITE,
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_valor_gris = _fmt(
        font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color=_hex_to_xlsxwriter(LIGHT_GRAY),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_alerta_header = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(ALTO_BG),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_ficha_alerta_row = _fmt(
        font_size=8, font_color=_hex_to_xlsxwriter(TEXT_DARK),
        bg_color='FEF9C3',
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )

    def _nivel_fmt(nivel: str):
        return {
            'CRÍTICO': fmt_critico,
            'ALTO':    fmt_alto,
            'MEDIO':   fmt_medio,
            'BAJO':    fmt_bajo,
        }.get(nivel, fmt_dato)

    def _nivel_bg(nivel: str) -> str:
        return {
            'CRÍTICO': _hex_to_xlsxwriter(CRITICO_BG),
            'ALTO':    _hex_to_xlsxwriter(ALTO_BG),
            'MEDIO':   _hex_to_xlsxwriter(MEDIO_BG),
            'BAJO':    _hex_to_xlsxwriter(BAJO_BG),
        }.get(nivel, 'FFFFFF')

    def _flag_fmt(val: int):
        return fmt_flag_yes if val else fmt_flag_no

    def _flag_str(val: int) -> str:
        return '✔' if val else '·'

    today_str = dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 1: Resumen Ejecutivo
    # ════════════════════════════════════════════════════════════════════════
    ws1 = wb.add_worksheet('Resumen Ejecutivo')
    ws1.set_tab_color(_hex_to_xlsxwriter(NAVY))
    ws1.hide_gridlines(2)
    ws1.set_column('A:A', 38)
    ws1.set_column('B:B', 22)
    ws1.set_column('C:C', 22)
    ws1.set_column('D:D', 22)
    ws1.set_column('E:E', 18)

    # Fila 0: título
    ws1.set_row(0, 30)
    ws1.merge_range('A1:E1', 'ANÁLISIS AML INDIVIDUAL — Global66', fmt_titulo)

    # Fila 1: subtítulo
    ws1.set_row(1, 22)
    ws1.merge_range('A2:E2', f'Generado: {today_str} | Clientes analizados: {n_clientes}', fmt_subtitulo)

    # Fila 3: KPIs
    ws1.set_row(3, 22)
    ws1.merge_range('A4:E4', 'KPIs GLOBALES', fmt_seccion)

    kpis = [
        ('Total Transacciones (IN+OUT+CashCall)', total_txs_all),
        ('  · de las cuales Cash Call Pay-In', n_cashcall),
        ('Txs Exitosas Analizadas', total_txs_exitosas),
        ('Clientes Analizados', n_clientes),
        (f'Volumen Total USD', f'{vol_total_usd:,.2f}'),
        (f'Ticket Promedio USD', f'{ticket_prom:,.2f}'),
        ('Beneficiarios Únicos (OUT)', bene_unicos_total),
        ('Beneficiarios Multi-Registro', bene_multi),
        ('Txs a Países de Riesgo', txs_pais_riesgo),
    ]
    for i, (label, val) in enumerate(kpis):
        row = 4 + i
        ws1.set_row(row, 18)
        fmt_row = fmt_dato if i % 2 == 0 else fmt_dato_gris
        ws1.write(row, 0, label, fmt_row)
        ws1.write(row, 1, val, fmt_row)

    # Distribución por nivel
    r_sec = 4 + len(kpis) + 1
    ws1.set_row(r_sec, 22)
    ws1.merge_range(r_sec, 0, r_sec, 4, 'DISTRIBUCIÓN POR NIVEL DE RIESGO', fmt_seccion)

    r_sec += 1
    ws1.set_row(r_sec, 22)
    for ci, h in enumerate(['Nivel', 'Clientes', '% Clientes', 'Volumen USD', '% Volumen']):
        ws1.write(r_sec, ci, h, fmt_header)

    for i, nivel in enumerate(['CRÍTICO', 'ALTO', 'MEDIO', 'BAJO']):
        r = r_sec + 1 + i
        ws1.set_row(r, 18)
        d = by_nivel[nivel]
        pct_cl = d['clientes'] / total_clientes_con_data if total_clientes_con_data > 0 else 0
        pct_vol = d['vol'] / total_vol_con_data if total_vol_con_data > 0 else 0
        nfmt = _nivel_fmt(nivel)
        ws1.write(r, 0, nivel, nfmt)
        ws1.write(r, 1, d['clientes'], nfmt)
        ws1.write(r, 2, f'{pct_cl:.1%}', nfmt)
        ws1.write(r, 3, f"{d['vol']:,.2f}", nfmt)
        ws1.write(r, 4, f'{pct_vol:.1%}', nfmt)

    # Alertas por indicador
    r_ind = r_sec + 6
    ws1.set_row(r_ind, 22)
    ws1.merge_range(r_ind, 0, r_ind, 4, 'ALERTAS POR INDICADOR', fmt_seccion)

    r_ind += 1
    ws1.set_row(r_ind, 22)
    for ci, h in enumerate(['Indicador', 'Clientes con Flag', 'Peso', 'Score Aportado']):
        ws1.write(r_ind, ci, h, fmt_header)

    flag_keys = list(FLAG_WEIGHTS.keys())
    for i, fk in enumerate(flag_keys):
        r = r_ind + 1 + i
        ws1.set_row(r, 18)
        n_con_flag = sum(1 for f in flags_map.values() if f.get(fk, 0))
        peso = FLAG_WEIGHTS[fk]
        score_total = n_con_flag * peso
        fmt_row = fmt_dato if i % 2 == 0 else fmt_dato_gris
        ws1.write(r, 0, FLAG_LABELS[fk], fmt_row)
        ws1.write(r, 1, n_con_flag, fmt_row)
        ws1.write(r, 2, peso, fmt_row)
        ws1.write(r, 3, score_total, fmt_row)

    # Hallazgos críticos
    r_hall = r_ind + len(flag_keys) + 2
    ws1.set_row(r_hall, 22)
    ws1.merge_range(r_hall, 0, r_hall, 4, 'HALLAZGOS CRÍTICOS', fmt_hallazgo_header)

    for j, h in enumerate(hallazgos):
        r = r_hall + 1 + j * 2
        ws1.set_row(r, 22)
        ws1.set_row(r + 1, 40)
        ws1.write(r, 0, f"#{h['num']}", fmt_hallazgo_num)
        ws1.merge_range(r, 1, r, 4, h['hallazgo'], fmt_hallazgo_titulo)
        ws1.merge_range(r + 1, 0, r + 1, 4, h['descripcion'], fmt_hallazgo_desc)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 2: 🎯 Scoring Clientes
    # ════════════════════════════════════════════════════════════════════════
    ws2 = wb.add_worksheet('🎯 Scoring Clientes')
    ws2.set_tab_color('DC2626')
    ws2.hide_gridlines(2)

    # Headers exactos en el orden especificado
    scoring_headers = [
        'ID Cliente', 'Nombre', 'Email', 'Txs Exitosas', 'Txs Total',
        'Total USD', 'Máx Tx USD', 'Score', 'Nivel',
        '🚩Struct.≥2tx(w=3)', '🚩Veloc.≥5/d(w=2)', '🚩Fan-Out≥5(w=2)', '🚩M.Alto≥2tx(w=2)',
        '🚩País Riesgo(w=3)', '🚩Redond.(w=1)', '🚩Dev.(w=2)', '🚩Conc.(w=1)',
        '🚩Crec.(w=2)', '🚩DivGeo(w=1)',
        'N Txs Struct.', 'Max Txs/día', 'N Benef Distinct', 'Txs ≥10K',
        '% Montos Redondos', 'N Dev.', 'Tasa Dev %', 'Conc. %',
        'Ratio Crec.', 'N Países Dest.', 'Países Riesgo',
    ]
    # Anchos de columna: ID=13, Nombre=24, Email=28, Txs Ex=10, Txs Tot=10,
    # Total USD=14, Max Tx=14, Score=8, Nivel=10, Flags=8 cada uno (x10),
    # métricas=12 cada uno (x10), Países Riesgo=20
    col_widths_s2 = [13, 24, 28, 10, 10, 14, 14, 8, 10,
                     8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
                     12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 20]

    ws2.set_row(0, 30)
    ws2.merge_range(0, 0, 0, len(scoring_headers) - 1, 'SCORING DE RIESGO — Clientes Individuales', fmt_titulo)
    ws2.set_row(1, 22)
    ws2.merge_range(1, 0, 1, len(scoring_headers) - 1, f'Generado: {today_str}', fmt_subtitulo)
    ws2.set_row(2, 22)
    for ci, h in enumerate(scoring_headers):
        ws2.write(2, ci, h, fmt_header)
        ws2.set_column(ci, ci, col_widths_s2[ci])

    ws2.freeze_panes(3, 9)
    ws2.autofilter(2, 0, 2, len(scoring_headers) - 1)

    sorted_flags = sorted(flags_map.values(), key=lambda x: x['risk_score'], reverse=True)
    for ri, f in enumerate(sorted_flags):
        row = 3 + ri
        ws2.set_row(row, 18)
        nivel = f['nivel_riesgo']
        nfmt = _nivel_fmt(nivel)

        ws2.write(row, 0, f['customer_id'], fmt_dato)
        ws2.write(row, 1, f['customer_name'], fmt_dato)
        ws2.write(row, 2, f['customer_email'], fmt_dato)
        ws2.write(row, 3, f['n_txs_exitosas'], fmt_dato_int)
        ws2.write(row, 4, f['n_txs_total'], fmt_dato_int)
        ws2.write(row, 5, f['vol_total_usd'], fmt_dato_num)
        ws2.write(row, 6, f['max_tx_usd'], fmt_dato_num)
        ws2.write(row, 7, f['risk_score'], nfmt)
        ws2.write(row, 8, nivel, nfmt)

        flag_keys_order = [
            'flag_structuring', 'flag_velocidad', 'flag_fanout', 'flag_monto_alto',
            'flag_pais_riesgo', 'flag_redondos', 'flag_devolucion', 'flag_concentracion',
            'flag_crecimiento', 'flag_diversif',
        ]
        for fi, fk in enumerate(flag_keys_order):
            val = f.get(fk, 0)
            ws2.write(row, 9 + fi, _flag_str(val), _flag_fmt(val))

        # Métricas de soporte (columnas 19-30)
        ws2.write(row, 19, f['n_structuring_txs'], fmt_dato_int)
        ws2.write(row, 20, f['max_txs_per_day'], fmt_dato_int)
        ws2.write(row, 21, f['n_beneficiarios'], fmt_dato_int)
        ws2.write(row, 22, f['n_txs_monto_alto'], fmt_dato_int)
        ws2.write(row, 23, f'{f["pct_redondos"]:.1%}', fmt_dato_center)
        ws2.write(row, 24, f['n_devuelto'], fmt_dato_int)
        ws2.write(row, 25, f'{f["tasa_devolucion_pct"]:.1%}', fmt_dato_center)
        ws2.write(row, 26, f'{f["max_concentracion_pct"]:.1f}%' if f['max_concentracion_pct'] else '0.0%', fmt_dato_center)
        ws2.write(row, 27, f['ratio_crecimiento'], fmt_dato_num)
        ws2.write(row, 28, f['n_paises_destino'], fmt_dato_int)
        ws2.write(row, 29, f['paises_riesgo'] or '—', fmt_dato)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 3: 🔴 Clientes Alto Riesgo — FORMATO FICHA VERTICAL
    # ════════════════════════════════════════════════════════════════════════
    ws3 = wb.add_worksheet('🔴 Clientes Alto Riesgo')
    ws3.set_tab_color('DC2626')
    ws3.hide_gridlines(2)

    ws3.set_column('A:A', 22)
    ws3.set_column('B:B', 30)
    ws3.set_column('C:C', 16)
    ws3.set_column('D:D', 16)
    ws3.set_column('E:E', 16)
    ws3.set_column('F:F', 16)

    ws3.set_row(0, 30)
    ws3.merge_range(0, 0, 0, 5, 'CLIENTES CRÍTICO Y ALTO RIESGO — Fichas Detalle', fmt_titulo)
    ws3.set_row(1, 22)
    ws3.merge_range(1, 0, 1, 5, f'Generado: {today_str}', fmt_subtitulo)

    alto_riesgo = [f for f in flags_map.values() if f['nivel_riesgo'] in ('CRÍTICO', 'ALTO')]
    alto_riesgo.sort(key=lambda x: x['risk_score'], reverse=True)

    current_row = 2

    for f in alto_riesgo:
        nivel = f['nivel_riesgo']
        cid = f['customer_id']

        # Cabecera del cliente (merge A:F, fondo según nivel)
        cabecera_fmt = fmt_ficha_critico if nivel == 'CRÍTICO' else fmt_ficha_alto
        cabecera_txt = f"[{nivel}] | ID: {cid} | {f['customer_name']} | {f['customer_email']}"
        ws3.set_row(current_row, 26)
        ws3.merge_range(current_row, 0, current_row, 5, cabecera_txt, cabecera_fmt)
        current_row += 1

        # Flags activos
        flag_names = [FLAG_LABELS[fk] for fk in FLAG_WEIGHTS if f.get(fk, 0)]
        flags_str = ', '.join(
            fk.replace('flag_structuring', 'F1-Struct').replace('flag_velocidad', 'F2-Veloc')
              .replace('flag_fanout', 'F3-FanOut').replace('flag_monto_alto', 'F4-MAlto')
              .replace('flag_pais_riesgo', 'F5-País').replace('flag_redondos', 'F6-Redond')
              .replace('flag_devolucion', 'F7-Dev').replace('flag_concentracion', 'F8-Conc')
              .replace('flag_crecimiento', 'F9-Crec').replace('flag_diversif', 'F10-DivGeo')
            for fk in FLAG_WEIGHTS if f.get(fk, 0)
        ) or '—'

        # Datos en 2 columnas (Label | Valor), alternando fondo blanco/gris
        ficha_datos = [
            ('ID Cliente',        str(cid)),
            ('Email',             f['customer_email']),
            ('Txs Exitosas',      str(f['n_txs_exitosas'])),
            ('Txs Total',         str(f['n_txs_total'])),
            ('Volumen USD',       f"${f['vol_total_usd']:,.2f}"),
            ('Máx. Tx USD',       f"${f['max_tx_usd']:,.2f}"),
            ('N° Beneficiarios',  str(f['n_beneficiarios'])),
            ('N° Países Destino', str(f['n_paises_destino'])),
            ('Países Riesgo',     f['paises_riesgo'] or '—'),
            ('Score de Riesgo',   str(f['risk_score'])),
            ('Nivel',             nivel),
            ('Flags Activos',     flags_str),
        ]

        for idx, (label, valor) in enumerate(ficha_datos):
            ws3.set_row(current_row, 18)
            lbl_fmt = fmt_ficha_label
            val_fmt = fmt_ficha_valor if idx % 2 == 0 else fmt_ficha_valor_gris
            ws3.write(current_row, 0, label, lbl_fmt)
            ws3.write(current_row, 1, valor, val_fmt)
            # columnas C-F en blanco con borde
            for col in range(2, 6):
                ws3.write(current_row, col, '', val_fmt)
            current_row += 1

        # Sub-sección ALERTAS ACTIVAS
        ws3.set_row(current_row, 20)
        ws3.merge_range(current_row, 0, current_row, 5, 'ALERTAS ACTIVAS', fmt_ficha_alerta_header)
        current_row += 1

        # Headers alertas
        ws3.set_row(current_row, 18)
        for ci, h in enumerate(['Tipo', 'Tx ID', 'Fecha', 'Monto USD', 'País', 'Beneficiario']):
            ws3.write(current_row, ci, h, fmt_header)
        current_row += 1

        # Txs del cliente que activaron alertas
        cid_txs = txs_by_customer.get(cid, [])
        alerta_txs = []
        for r in cid_txs:
            amt = _to_float(r.get('origin_amount_usd'))
            country = r.get('destiny_country') or ''
            if 8000.0 <= amt <= 9999.99 and r.get('flujo') == 'OUT':
                alerta_txs.append(('STRUCTURING', r, amt, country))
            elif amt >= 10000.0:
                alerta_txs.append(('MONTO ALTO', r, amt, country))
            elif country in HIGH_RISK_COUNTRIES:
                alerta_txs.append(('PAÍS RIESGO', r, amt, country))

        if not alerta_txs:
            ws3.set_row(current_row, 18)
            ws3.merge_range(current_row, 0, current_row, 5, '(sin alertas detalladas)', fmt_dato)
            current_row += 1
        else:
            for tipo, r, amt, country in alerta_txs:
                ws3.set_row(current_row, 18)
                bene_name = r.get('beneficiary_name', '') or ''
                bene_last = r.get('beneficiary_last_name', '') or ''
                bene_full = f"{bene_name} {bene_last}".strip()
                ws3.write(current_row, 0, tipo, fmt_ficha_alerta_row)
                ws3.write(current_row, 1, str(r.get('transaction_id', '')), fmt_ficha_alerta_row)
                ws3.write(current_row, 2, str(r.get('start_date', '')), fmt_ficha_alerta_row)
                ws3.write(current_row, 3, amt, fmt_ficha_alerta_row)
                ws3.write(current_row, 4, country, fmt_ficha_alerta_row)
                ws3.write(current_row, 5, bene_full, fmt_ficha_alerta_row)
                current_row += 1

        # 2 filas en blanco entre clientes
        ws3.set_row(current_row, 10)
        current_row += 1
        ws3.set_row(current_row, 10)
        current_row += 1

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 4: ⚠️ Alertas Detalladas
    # ════════════════════════════════════════════════════════════════════════
    ws4 = wb.add_worksheet('⚠️ Alertas Detalladas')
    ws4.set_tab_color(_hex_to_xlsxwriter(ALTO_BG))
    ws4.hide_gridlines(2)

    ws4.set_row(0, 30)
    ws4.merge_range(0, 0, 0, 9, 'ALERTAS DETALLADAS — Transacciones que Activan Indicadores', fmt_titulo)
    ws4.set_row(1, 22)
    ws4.merge_range(1, 0, 1, 9, f'Generado: {today_str}', fmt_subtitulo)
    ws4.set_row(2, 22)

    alerta_headers = [
        'Tipo Alerta', 'ID Cliente', 'Nombre', 'ID Tx',
        'Fecha', 'Monto USD', 'País Destino',
        'Beneficiario', 'Cédula Benef.', 'Detalle',
    ]
    col_widths_a4 = [15, 15, 22, 20, 20, 16, 18, 22, 20, 35]
    for ci, h in enumerate(alerta_headers):
        ws4.write(2, ci, h, fmt_header)
        ws4.set_column(ci, ci, col_widths_a4[ci])

    ws4.freeze_panes(3, 2)
    ws4.autofilter(2, 0, 2, len(alerta_headers) - 1)

    # Build alert rows — mostrar TODAS las txs (no solo las que tienen beneficiary_identification)
    alert_rows = []
    for r in rows:
        amt = _to_float(r.get('origin_amount_usd'))
        country = r.get('destiny_country') or ''
        if 8000.0 <= amt <= 9999.99 and r.get('flujo') == 'OUT':
            detalle = f"${amt:,.2f} en rango $8,000–$9,999 (posible fraccionamiento)"
            alert_rows.append(('STRUCTURING', r, detalle))
        if amt >= 10000.0:
            detalle = f"${amt:,.2f} supera umbral de reporte $10,000 USD"
            alert_rows.append(('MONTO ALTO', r, detalle))
        if country in HIGH_RISK_COUNTRIES:
            detalle = f"Destino {country} — jurisdicción FATF/OFAC de alto riesgo"
            alert_rows.append(('PAÍS RIESGO', r, detalle))

    fmt_map_alerta = {
        'STRUCTURING': fmt_alerta_struct,
        'MONTO ALTO':  fmt_alerta_alto,
        'PAÍS RIESGO': fmt_alerta_pais,
    }
    for ri, (tipo, r, detalle) in enumerate(alert_rows):
        row = 3 + ri
        ws4.set_row(row, 18)
        afmt = fmt_map_alerta.get(tipo, fmt_dato)
        ws4.write(row, 0, tipo, afmt)
        ws4.write(row, 1, r.get('customer_id', ''), afmt)
        # Nombre = customer_name (no separar apellido)
        nombre = r.get('customer_name', '') or ''
        ws4.write(row, 2, nombre, afmt)
        ws4.write(row, 3, r.get('transaction_id', ''), afmt)
        start_str = str(r.get('start_date', ''))
        ws4.write(row, 4, start_str, afmt)
        ws4.write(row, 5, _to_float(r.get('origin_amount_usd')), afmt)
        ws4.write(row, 6, r.get('destiny_country', ''), afmt)
        bene_name = r.get('beneficiary_name', '') or ''
        bene_last = r.get('beneficiary_last_name', '') or ''
        ws4.write(row, 7, f"{bene_name} {bene_last}".strip(), afmt)
        ws4.write(row, 8, r.get('beneficiary_identification', ''), afmt)
        ws4.write(row, 9, detalle, afmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 5: 👥 Red de Beneficiarios
    # ════════════════════════════════════════════════════════════════════════
    ws5 = wb.add_worksheet('👥 Red de Beneficiarios')
    ws5.set_tab_color('2563EB')
    ws5.hide_gridlines(2)

    ws5.set_row(0, 30)
    ws5.merge_range(0, 0, 0, 11, 'RED DE BENEFICIARIOS — Fan-In Analysis', fmt_titulo)
    ws5.set_row(1, 22)
    ws5.merge_range(1, 0, 1, 11, 'Todos los beneficiarios con identificación registrada', fmt_subtitulo)
    ws5.set_row(2, 22)
    ws5.merge_range(2, 0, 2, 11, f'Generado: {today_str}', fmt_seccion)
    ws5.set_row(3, 22)

    # Headers exactos en el orden especificado
    fanin_headers = [
        'Identificación', 'Nombre', 'Apellido', 'País', 'Tipo Doc.',
        'Clientes Únicos', 'Bene IDs Distintos', 'Multi-registro',
        'Cuentas Distintas', 'Total Txs', 'Total USD', 'Nivel Fan-In',
    ]
    col_widths_f5 = [20, 22, 22, 15, 12, 14, 14, 14, 14, 10, 14, 12]
    ws5.set_row(4, 22)
    for ci, h in enumerate(fanin_headers):
        ws5.write(4, ci, h, fmt_header)
        ws5.set_column(ci, ci, col_widths_f5[ci])

    ws5.freeze_panes(5, 3)
    ws5.autofilter(4, 0, 4, len(fanin_headers) - 1)

    # Mostrar TODOS (sin filtro de clientes_unicos)
    for ri, b in enumerate(fanin_rows):
        row = 5 + ri
        ws5.set_row(row, 18)
        cu = b['clientes_unicos']
        if cu >= 7:
            nivel_fi = 'CRÍTICO'
            nfmt_fi = fmt_critico
        elif cu >= 4:
            nivel_fi = 'ALTO'
            nfmt_fi = fmt_alto
        elif cu >= 2:
            nivel_fi = 'MODERADO'
            nfmt_fi = fmt_medio
        else:
            nivel_fi = 'NORMAL'
            nfmt_fi = fmt_bajo

        multi = b['bene_ids_distintos'] > 1
        multi_fmt = fmt_purple if multi else fmt_dato_center
        multi_str = 'Sí ⚠' if multi else ''

        ws5.write(row, 0, b['beneficiary_identification'], fmt_dato)
        ws5.write(row, 1, b.get('beneficiary_name', ''), fmt_dato)
        ws5.write(row, 2, b.get('beneficiary_last_name', ''), fmt_dato)
        ws5.write(row, 3, b.get('beneficiary_country_code', ''), fmt_dato)
        ws5.write(row, 4, b.get('beneficiary_identification_type', ''), fmt_dato)
        ws5.write(row, 5, b['clientes_unicos'], nfmt_fi)
        ws5.write(row, 6, b['bene_ids_distintos'], fmt_dato_int)
        ws5.write(row, 7, multi_str, multi_fmt)
        ws5.write(row, 8, b['cuentas_distintas'], fmt_dato_int)
        ws5.write(row, 9, b['total_txs'], fmt_dato_int)
        ws5.write(row, 10, b['total_usd'], fmt_dato_num)
        ws5.write(row, 11, nivel_fi, nfmt_fi)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 6 NUEVA: 🌍 Corredores Remesas
    # ════════════════════════════════════════════════════════════════════════
    ws6 = wb.add_worksheet('🌍 Corredores Remesas')
    ws6.set_tab_color('2563EB')
    ws6.hide_gridlines(2)

    ws6.set_row(0, 30)
    ws6.merge_range(0, 0, 0, 7, 'CORREDORES DE REMESAS — Análisis por Par de Países', fmt_titulo)
    ws6.set_row(1, 22)
    ws6.merge_range(1, 0, 1, 7, f'Generado: {today_str} | Solo txs OUT exitosas', fmt_subtitulo)
    ws6.set_row(2, 22)

    corredor_headers = [
        'País Origen', 'País Destino', 'Total Txs', 'Clientes',
        'Benef. Únicos', 'Total USD', 'Promedio USD', 'País FATF',
    ]
    col_widths_c6 = [20, 20, 12, 12, 14, 16, 16, 12]
    for ci, h in enumerate(corredor_headers):
        ws6.write(2, ci, h, fmt_header)
        ws6.set_column(ci, ci, col_widths_c6[ci])

    ws6.freeze_panes(3, 2)
    ws6.autofilter(2, 0, 2, len(corredor_headers) - 1)

    for ri, c in enumerate(corredores):
        row = 3 + ri
        ws6.set_row(row, 18)
        if c['es_pais_riesgo']:
            rfmt = fmt_critico
            rfmt_num = fmt_critico
        else:
            rfmt = fmt_dato if ri % 2 == 0 else fmt_dato_gris
            rfmt_num = fmt_dato_num if ri % 2 == 0 else fmt_dato_gris_num
        ws6.write(row, 0, c['origin_country'], rfmt)
        ws6.write(row, 1, c['destiny_country'], rfmt)
        ws6.write(row, 2, c['total_txs'], rfmt)
        ws6.write(row, 3, c['clientes_unicos'], rfmt)
        ws6.write(row, 4, c['beneficiarios_unicos'], rfmt)
        ws6.write(row, 5, c['total_usd'], rfmt_num)
        ws6.write(row, 6, c['promedio_usd'], rfmt_num)
        ws6.write(row, 7, 'SI' if c['es_pais_riesgo'] else 'No', rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 7: Métodos de Pago
    # ════════════════════════════════════════════════════════════════════════
    ws7 = wb.add_worksheet('Métodos de Pago')
    ws7.set_tab_color(_hex_to_xlsxwriter(PURPLE))
    ws7.hide_gridlines(2)

    ws7.set_row(0, 30)
    ws7.merge_range(0, 0, 0, 4, 'MÉTODOS DE PAGO — Distribución', fmt_titulo)
    ws7.set_row(1, 22)
    ws7.merge_range(1, 0, 1, 4, f'Generado: {today_str}', fmt_subtitulo)
    ws7.set_row(2, 22)

    metodo_headers = ['payment_method', 'txns', '% txns', 'vol_usd', 'clientes_unicos']
    col_widths_m7 = [22, 10, 10, 16, 16]
    for ci, h in enumerate(metodo_headers):
        ws7.write(2, ci, h, fmt_header)
        ws7.set_column(ci, ci, col_widths_m7[ci])

    ws7.freeze_panes(3, 1)
    ws7.autofilter(2, 0, 2, len(metodo_headers) - 1)

    total_method_txns = sum(m['txns'] for m in metodos)
    for ri, m in enumerate(metodos):
        row = 3 + ri
        ws7.set_row(row, 18)
        pct = m['txns'] / total_method_txns if total_method_txns > 0 else 0
        dominant = pct > 0.80
        rfmt = fmt_critico if dominant else (fmt_dato if ri % 2 == 0 else fmt_dato_gris)
        ws7.write(row, 0, m['payment_method'], rfmt)
        ws7.write(row, 1, m['txns'], rfmt)
        ws7.write(row, 2, f'{pct:.1%}', rfmt)
        ws7.write(row, 3, m['vol_usd'], rfmt)
        ws7.write(row, 4, m['clientes_unicos'], rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 8: Nacionalidades
    # ════════════════════════════════════════════════════════════════════════
    ws8 = wb.add_worksheet('Nacionalidades')
    ws8.set_tab_color(_hex_to_xlsxwriter(ALTO_BG))
    ws8.hide_gridlines(2)

    ws8.set_row(0, 30)
    ws8.merge_range(0, 0, 0, 3, 'NACIONALIDADES DE CLIENTES', fmt_titulo)
    ws8.set_row(1, 22)
    ws8.merge_range(1, 0, 1, 3, f'Generado: {today_str}', fmt_subtitulo)
    ws8.set_row(2, 22)

    has_nationality = any(r.get('nationality_code') is not None for r in rows)

    if not has_nationality:
        ws8.merge_range(2, 0, 2, 3, 'Datos de nacionalidad no disponibles en esta query', fmt_seccion)
    else:
        nat_headers = ['nationality_code', 'txns', 'clientes', 'vol_usd']
        col_widths_n8 = [20, 10, 10, 16]
        for ci, h in enumerate(nat_headers):
            ws8.write(2, ci, h, fmt_header)
            ws8.set_column(ci, ci, col_widths_n8[ci])

        ws8.freeze_panes(3, 1)
        ws8.autofilter(2, 0, 2, len(nat_headers) - 1)

        by_nat: dict = defaultdict(lambda: {'txns': 0, 'customers': set(), 'vol': 0.0})
        for r in rows:
            nat = r.get('nationality_code') or 'DESCONOCIDO'
            by_nat[nat]['txns'] += 1
            cid = r.get('customer_id')
            if cid:
                by_nat[nat]['customers'].add(cid)
            by_nat[nat]['vol'] += _to_float(r.get('origin_amount_usd'))

        nat_data = sorted(by_nat.items(), key=lambda x: x[1]['txns'], reverse=True)
        for ri, (nat, data) in enumerate(nat_data):
            row = 3 + ri
            ws8.set_row(row, 18)
            rfmt = fmt_dato if ri % 2 == 0 else fmt_dato_gris
            ws8.write(row, 0, nat, rfmt)
            ws8.write(row, 1, data['txns'], rfmt)
            ws8.write(row, 2, len(data['customers']), rfmt)
            ws8.write(row, 3, round(data['vol'], 2), rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 9: 📈 Evolución Mensual (ampliada con IN/OUT y sección comparativa)
    # ════════════════════════════════════════════════════════════════════════
    ws9 = wb.add_worksheet('📈 Evolución Mensual')
    ws9.set_tab_color('16A34A')
    ws9.hide_gridlines(2)

    ws9.set_row(0, 30)
    ws9.merge_range(0, 0, 0, 6, 'EVOLUCIÓN MENSUAL — Volumen y Transacciones', fmt_titulo)
    ws9.set_row(1, 22)
    ws9.merge_range(1, 0, 1, 6, f'Generado: {today_str}', fmt_subtitulo)
    ws9.set_row(2, 22)

    # ── Sección 1: tabla principal (A-G)
    evol_headers_1 = ['Mes', 'Total Txs', 'Total USD', 'Clientes Activos', 'Benef. Únicos', '% vs Promedio', 'Alerta']
    col_widths_e9 = [14, 12, 16, 16, 14, 16, 14]
    for ci, h in enumerate(evol_headers_1):
        ws9.write(2, ci, h, fmt_header)
        ws9.set_column(ci, ci, col_widths_e9[ci])

    # Calcular promedio de vol mensual
    total_vol_evol = sum(e['vol_usd'] for e in evolucion)
    n_meses = len(evolucion)
    promedio_vol_mensual = total_vol_evol / n_meses if n_meses > 0 else 0.0

    # Formato para fila "pico"
    fmt_pico_row = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='center', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_pico_left = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='left', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
    )
    fmt_pico_num = _fmt(
        bold=True, font_size=9, font_color=WHITE,
        bg_color=_hex_to_xlsxwriter(CRITICO_BG),
        align='right', valign='vcenter',
        border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
        num_format='#,##0.00',
    )

    for ri, e in enumerate(evolucion):
        row = 3 + ri
        ws9.set_row(row, 18)
        vol_mes = e['vol_usd']
        pct_vs_prom = (vol_mes / promedio_vol_mensual - 1) if promedio_vol_mensual > 0 else 0.0
        alerta_str = '⚠ Pico' if pct_vs_prom > 0.50 else '✓ Normal'
        es_pico = pct_vs_prom > 0.50

        if es_pico:
            ws9.write(row, 0, e['mes'], fmt_pico_left)
            ws9.write(row, 1, e['txns'], fmt_pico_row)
            ws9.write(row, 2, e['vol_usd'], fmt_pico_num)
            ws9.write(row, 3, e['clientes_activos'], fmt_pico_row)
            ws9.write(row, 4, e['benef_unicos'], fmt_pico_row)
            ws9.write(row, 5, f'{pct_vs_prom:+.1%}', fmt_pico_row)
            ws9.write(row, 6, alerta_str, fmt_pico_row)
        else:
            rfmt = fmt_dato if ri % 2 == 0 else fmt_dato_gris
            rfmt_center = fmt_dato_center if ri % 2 == 0 else _fmt(
                font_size=9, font_color=_hex_to_xlsxwriter(TEXT_DARK),
                bg_color=_hex_to_xlsxwriter(LIGHT_GRAY),
                align='center', valign='vcenter',
                border=1, border_color=_hex_to_xlsxwriter(BORDER_COL),
            )
            ws9.write(row, 0, e['mes'], rfmt)
            ws9.write(row, 1, e['txns'], rfmt)
            ws9.write(row, 2, e['vol_usd'], rfmt)
            ws9.write(row, 3, e['clientes_activos'], rfmt)
            ws9.write(row, 4, e['benef_unicos'], rfmt)
            ws9.write(row, 5, f'{pct_vs_prom:+.1%}', rfmt_center)
            ws9.write(row, 6, alerta_str, rfmt_center)

    # Separador (fila en blanco)
    separador_row = 3 + n_meses + 1
    ws9.set_row(separador_row - 1, 10)

    # ── Sección 2: Comparativa IN vs OUT
    sec2_start = 3 + n_meses + 2
    ws9.set_row(sec2_start, 22)
    ws9.merge_range(sec2_start, 0, sec2_start, 5,
                    'COMPARATIVA IN vs OUT — Por Mes',
                    _fmt(bold=True, font_size=10, font_color=WHITE,
                         bg_color=_hex_to_xlsxwriter(NAVY),
                         align='left', valign='vcenter'))

    evol_headers_2 = ['Mes', 'Txs OUT', 'USD OUT', 'Txs IN', 'USD IN', 'Ratio OUT/IN']
    col_widths_e9_s2 = [14, 12, 16, 12, 16, 14]
    for ci, h in enumerate(evol_headers_2):
        ws9.write(sec2_start + 1, ci, h, fmt_header)
        ws9.set_column(ci, ci, max(col_widths_e9[ci] if ci < len(col_widths_e9) else 14,
                                   col_widths_e9_s2[ci]))

    for ri, e in enumerate(evolucion):
        row = sec2_start + 2 + ri
        ws9.set_row(row, 18)
        rfmt = fmt_dato if ri % 2 == 0 else fmt_dato_gris
        rfmt_num2 = fmt_dato_num if ri % 2 == 0 else fmt_dato_gris_num
        vol_out = e['vol_out']
        vol_in = e['vol_in']
        ratio = round(vol_out / vol_in, 4) if vol_in > 0 else None
        ws9.write(row, 0, e['mes'], rfmt)
        ws9.write(row, 1, e['txns_out'], rfmt)
        ws9.write(row, 2, vol_out, rfmt_num2)
        ws9.write(row, 3, e['txns_in'], rfmt)
        ws9.write(row, 4, vol_in, rfmt_num2)
        if ratio is not None:
            ws9.write(row, 5, ratio, rfmt_num2)
        else:
            ws9.write(row, 5, 'N/A', rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 10: Análisis Horario
    # ════════════════════════════════════════════════════════════════════════
    ws10 = wb.add_worksheet('Análisis Horario')
    ws10.set_tab_color('0891B2')
    ws10.hide_gridlines(2)

    ws10.set_row(0, 30)
    ws10.merge_range(0, 0, 0, 4, 'ANÁLISIS HORARIO — Distribución de Transacciones por Hora', fmt_titulo)
    ws10.set_row(1, 22)
    ws10.merge_range(1, 0, 1, 4, f'Generado: {today_str}', fmt_subtitulo)
    ws10.set_row(2, 22)

    hora_headers = ['hora', 'franja', 'txns', 'vol_usd', '% del total']
    col_widths_h10 = [8, 18, 10, 16, 12]
    for ci, h in enumerate(hora_headers):
        ws10.write(2, ci, h, fmt_header)
        ws10.set_column(ci, ci, col_widths_h10[ci])

    total_horario_txns = sum(h['txns'] for h in horario)
    madrugada_pct = sum(
        h['txns'] for h in horario if 0 <= h['hora'] <= 5
    ) / total_horario_txns if total_horario_txns > 0 else 0

    for ri, h_row in enumerate(horario):
        row = 3 + ri
        ws10.set_row(row, 18)
        pct = h_row['txns'] / total_horario_txns if total_horario_txns > 0 else 0
        is_madrugada = (0 <= h_row['hora'] <= 5) and madrugada_pct > 0.15
        rfmt = fmt_flag_yes if is_madrugada else (fmt_dato if ri % 2 == 0 else fmt_dato_gris)
        ws10.write(row, 0, h_row['hora'], rfmt)
        ws10.write(row, 1, h_row['franja'], rfmt)
        ws10.write(row, 2, h_row['txns'], rfmt)
        ws10.write(row, 3, h_row['vol_usd'], rfmt)
        ws10.write(row, 4, f'{pct:.1%}', rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 11: Países Destino
    # ════════════════════════════════════════════════════════════════════════
    ws11 = wb.add_worksheet('Países Destino')
    ws11.set_tab_color('2563EB')
    ws11.hide_gridlines(2)

    ws11.set_row(0, 30)
    ws11.merge_range(0, 0, 0, 4, 'PAÍSES DESTINO — Análisis Outbound', fmt_titulo)
    ws11.set_row(1, 22)
    ws11.merge_range(1, 0, 1, 4, f'Generado: {today_str}', fmt_subtitulo)
    ws11.set_row(2, 22)

    pais_headers = ['destiny_country', 'txns', 'vol_usd', 'clientes', 'es_pais_riesgo']
    col_widths_p11 = [22, 10, 16, 10, 16]
    for ci, h in enumerate(pais_headers):
        ws11.write(2, ci, h, fmt_header)
        ws11.set_column(ci, ci, col_widths_p11[ci])

    ws11.freeze_panes(3, 1)
    ws11.autofilter(2, 0, 2, len(pais_headers) - 1)

    for ri, p in enumerate(paises):
        row = 3 + ri
        ws11.set_row(row, 18)
        rfmt = fmt_critico if p['es_pais_riesgo'] else (fmt_dato if ri % 2 == 0 else fmt_dato_gris)
        ws11.write(row, 0, p['destiny_country'], rfmt)
        ws11.write(row, 1, p['txns'], rfmt)
        ws11.write(row, 2, p['vol_usd'], rfmt)
        ws11.write(row, 3, p['clientes_unicos'], rfmt)
        ws11.write(row, 4, 'SI' if p['es_pais_riesgo'] else 'No', rfmt)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 12: Metodología
    # ════════════════════════════════════════════════════════════════════════
    ws12 = wb.add_worksheet('Metodología')
    ws12.set_tab_color('6B7280')
    ws12.hide_gridlines(2)
    ws12.set_column('A:A', 30)
    ws12.set_column('B:B', 70)

    ws12.set_row(0, 30)
    ws12.merge_range(0, 0, 0, 1, 'METODOLOGÍA — Indicadores de Riesgo AML Individual', fmt_titulo)
    ws12.set_row(1, 22)
    ws12.merge_range(1, 0, 1, 1, f'WatchTower AML — Global66 Compliance | {today_str}', fmt_subtitulo)

    ws12.set_row(3, 22)
    ws12.merge_range(3, 0, 3, 1, 'DESCRIPCIÓN DE INDICADORES (FLAGS)', fmt_seccion)
    ws12.set_row(4, 22)
    ws12.write(4, 0, 'Flag', fmt_header)
    ws12.write(4, 1, 'Descripción y Umbral', fmt_header)

    metodologia = [
        ('F1 Estructuración (peso 3)',
         '2 o más transacciones OUT con monto entre USD 8.000 y USD 9.999,99. '
         'Indicador de fraccionamiento de montos para evadir el umbral de reporte de USD 10.000.'),
        ('F2 Velocidad (peso 2)',
         '5 o más transacciones en el mismo día calendario (date_only). '
         'Alta frecuencia intradiaria puede indicar urgencia o automatización sospechosa. '
         '(Umbral ajustado: en Global66, 3-4 txs diarias es comportamiento rutinario.)'),
        ('F3 Fan-Out (peso 2)',
         '5 o más beneficiarios distintos en transacciones OUT. '
         'Dispersión elevada de fondos a múltiples destinatarios, posible layering.'),
        ('F4 Monto Alto (peso 2)',
         '2 o más transacciones con monto >= USD 10.000 en el período analizado. '
         'La repetición de montos sobre umbral de reporte indica patrón sistemático, no transacción aislada. '
         '(Umbral ajustado: 1 sola tx de $10K es normal en remesas B2B de Global66.)'),
        ('F5 País Riesgo (peso 3)',
         'Transacción OUT con country_dest en lista de jurisdicciones de alto riesgo '
         '(FATF Call for Action + FATF Increased Monitoring + OFAC). '
         'Peso máximo por impacto regulatorio.'),
        ('F6 Montos Redondos (peso 1)',
         'Más del 70% de transacciones son múltiplos exactos de 1.000, 5.000, 10.000, 50.000 o 100.000 '
         '(mínimo 3 transacciones para activar). '
         'Montos redondos artificiales son indicador clásico de Smurfing.'),
        ('F7 Devolución (peso 2)',
         'Reservado para detección de transacciones revertidas o devoluciones anómalas. '
         'Actualmente siempre = 0 (implementación futura con datos de reversiones).'),
        ('F8 Concentración (peso 1)',
         'Un único beneficiario recibe más del 80% del volumen total OUT, '
         'con al menos 3 beneficiarios distintos en el período. '
         'Concentración extrema puede indicar relación controlada entre remitente y beneficiario.'),
        ('F9 Crecimiento (peso 2)',
         'Volumen en los últimos 30 días >= 3x el volumen de los 30 días previos, '
         'con volumen reciente > USD 5.000. '
         'Aumento abrupto inconsistente con perfil histórico.'),
        ('F10 Diversificación (peso 1)',
         'Envíos a 4 o más países destino distintos. '
         'Alta dispersión geográfica puede indicar búsqueda de jurisdicciones con menor control AML.'),
    ]

    for ri, (flag, desc) in enumerate(metodologia):
        row = 5 + ri
        ws12.set_row(row, 40)
        rfmt = fmt_dato if ri % 2 == 0 else fmt_dato_gris
        rfmt_desc = wb.add_format({
            'font_size': 9,
            'font_color': _hex_to_xlsxwriter(TEXT_DARK),
            'bg_color': 'FFFFFF' if ri % 2 == 0 else _hex_to_xlsxwriter(LIGHT_GRAY),
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': _hex_to_xlsxwriter(BORDER_COL),
            'text_wrap': True,
        })
        ws12.write(row, 0, flag, rfmt)
        ws12.write(row, 1, desc, rfmt_desc)

    # Niveles de riesgo
    r_niv = 5 + len(metodologia) + 2
    ws12.set_row(r_niv, 22)
    ws12.merge_range(r_niv, 0, r_niv, 1, 'NIVELES DE RIESGO Y UMBRALES DE SCORE', fmt_seccion)

    ws12.set_row(r_niv + 1, 22)
    ws12.write(r_niv + 1, 0, 'Nivel', fmt_header)
    ws12.write(r_niv + 1, 1, 'Rango de Score y Acción Recomendada', fmt_header)

    niveles_info = [
        ('CRÍTICO (score ≥ 10)', fmt_critico,
         'Score ≥ 10. Revisión inmediata obligatoria. Documentar investigación. '
         'Evaluar reporte de Operación Sospechosa (ROS) ante la UAF. '
         'Considerar bloqueo preventivo del perfil.'),
        ('ALTO (score 6-9)', fmt_alto,
         'Score 6-9. Revisión en 24-48h. Solicitar documentación adicional al cliente. '
         'Escalar a Oficial de Cumplimiento. Monitoreo reforzado.'),
        ('MEDIO (score 3-5)', fmt_medio,
         'Score 3-5. Revisión en el próximo ciclo regular (semanal). '
         'Verificar consistencia con perfil transaccional declarado. '
         'Actualizar evaluación de riesgo del cliente.'),
        ('BAJO (score 0-2)', fmt_bajo,
         'Score 0-2. Sin acción inmediata requerida. '
         'Mantener monitoreo periódico estándar. '
         'Revisar si aparecen nuevas transacciones en próximas ejecuciones.'),
    ]

    for ri, (nivel_str, nfmt, desc) in enumerate(niveles_info):
        row = r_niv + 2 + ri
        ws12.set_row(row, 40)
        rfmt_desc = wb.add_format({
            'font_size': 9,
            'font_color': _hex_to_xlsxwriter(TEXT_DARK),
            'bg_color': 'FFFFFF',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': _hex_to_xlsxwriter(BORDER_COL),
            'text_wrap': True,
        })
        ws12.write(row, 0, nivel_str, nfmt)
        ws12.write(row, 1, desc, rfmt_desc)

    # ════════════════════════════════════════════════════════════════════════
    # Hoja 13: 💰 CCA Cash Call Pay-In — fuente SEPARADA, sin flags/scoring.
    # Datos crudos de treasury.cash_call (type='CR'), independientes del motor
    # de arriba (remesas + CCA wallet_deposit).
    # ════════════════════════════════════════════════════════════════════════
    cashcall_rows = rows_cashcall_in or []
    ws13 = wb.add_worksheet('💰 CCA Cash Call Pay-In')
    ws13.set_tab_color('0EA5E9')
    ws13.hide_gridlines(2)

    cc_headers = [
        'Customer ID', 'Nombre', 'Email', 'Fecha Creación', 'Fecha Pago',
        'Cash Call ID', 'Referencia Externa', 'Monto', 'Monto USD Origen',
        'Monto USD Destino', 'Moneda', 'País Origen',
        'Remitente', 'DNI Remitente', 'Email Remitente', 'Banco',
    ]
    cc_widths = [12, 24, 28, 18, 18, 14, 20, 14, 16, 16, 10, 14, 24, 16, 26, 20]

    ws13.set_row(0, 30)
    ws13.merge_range(0, 0, 0, len(cc_headers) - 1, 'CCA CASH CALL — PAY IN (treasury.cash_call, type=CR)', fmt_titulo)
    ws13.set_row(1, 22)
    n_clientes_cc = len({r.get('customer_id') for r in cashcall_rows if r.get('customer_id') is not None})
    total_usd_cc = sum(_to_float(r.get('origin_amount_usd')) for r in cashcall_rows)
    ws13.merge_range(
        1, 0, 1, len(cc_headers) - 1,
        f'Generado: {today_str} | {len(cashcall_rows)} transacciones | '
        f'{n_clientes_cc} cliente(s) | Total USD {total_usd_cc:,.2f} — '
        'fuente independiente, no incluida en el scoring de riesgo de arriba',
        fmt_subtitulo,
    )
    ws13.set_row(2, 22)
    for ci, h in enumerate(cc_headers):
        ws13.write(2, ci, h, fmt_header)
        ws13.set_column(ci, ci, cc_widths[ci])

    ws13.freeze_panes(3, 2)
    ws13.autofilter(2, 0, 2, len(cc_headers) - 1)

    cashcall_sorted = sorted(
        cashcall_rows,
        key=lambda r: (r.get('customer_email') or '', str(r.get('start_date') or '')),
        reverse=False,
    )
    for ri, r in enumerate(cashcall_sorted):
        row = 3 + ri
        fmt_row = fmt_dato if ri % 2 == 0 else fmt_dato_gris
        fmt_row_num = fmt_dato_num if ri % 2 == 0 else fmt_dato_gris_num
        customer_name = f"{r.get('customer_name', '') or ''} {r.get('customer_last_name', '') or ''}".strip()
        remitente = f"{r.get('remitter_name', '') or ''} {r.get('remitter_lastname', '') or ''}".strip()
        ws13.write(row, 0, r.get('customer_id', ''), fmt_row)
        ws13.write(row, 1, customer_name, fmt_row)
        ws13.write(row, 2, r.get('customer_email', '') or '', fmt_row)
        ws13.write(row, 3, str(r.get('start_date', '') or ''), fmt_row)
        ws13.write(row, 4, str(r.get('paid_date', '') or ''), fmt_row)
        ws13.write(row, 5, r.get('cash_call_id', '') or '', fmt_row)
        ws13.write(row, 6, r.get('external_reference_number', '') or '', fmt_row)
        ws13.write(row, 7, _to_float(r.get('origin_amount')), fmt_row_num)
        ws13.write(row, 8, _to_float(r.get('origin_amount_usd')), fmt_row_num)
        ws13.write(row, 9, _to_float(r.get('destiny_amount_usd')), fmt_row_num)
        ws13.write(row, 10, r.get('origin_currency', '') or '', fmt_row)
        ws13.write(row, 11, r.get('origin_country', '') or '', fmt_row)
        ws13.write(row, 12, remitente, fmt_row)
        ws13.write(row, 13, r.get('remitter_dni', '') or '', fmt_row)
        ws13.write(row, 14, r.get('remitter_email', '') or '', fmt_row)
        ws13.write(row, 15, r.get('inbound_bank_name', '') or '', fmt_row)

    if not cashcall_rows:
        ws13.set_row(3, 18)
        ws13.merge_range(3, 0, 3, len(cc_headers) - 1,
                         '(sin transacciones de cash call pay-in en el período seleccionado)', fmt_dato)

    # Cierre y retorno
    wb.close()
    buf.seek(0)
    return buf.read()
