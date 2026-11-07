"""Esquemas Pydantic de la extracción estructurada. Son el primer guardrail
de la ingesta: si el LLM devuelve un canal inexistente, un porcentaje fuera
de rango o fechas invertidas, la validación falla y el documento no se carga."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Canal = Literal["Distribuidor", "Ferretería", "Constructora", "Retail moderno"]
# Grupo de productos (columna categoria).
Categoria = Literal["Planchas de yeso", "Placas cementicias", "Perfilería", "Tejas onduladas",
                    "Complementos", "Cielos rasos", "Ladrillos", "Cemento"]
Porcentaje = Field(ge=0, le=0.30, description="Fracción decimal: 3,5 % se expresa como 0.035")


class _ConVigencia(BaseModel):
    desde: date
    hasta: date

    @model_validator(mode="after")
    def _orden_fechas(self):
        if self.hasta < self.desde:
            raise ValueError("la fecha 'hasta' es anterior a 'desde'")
        return self


class TopeCanal(BaseModel):
    canal: Canal
    tope_pct: float = Porcentaje


class PoliticaExtraida(_ConVigencia):
    """Topes de descuento comercial en factura por canal."""
    topes: list[TopeCanal] = Field(min_length=1)


class FilaGrilla(_ConVigencia):
    codigo: str = Field(description="Código de la fila, p. ej. GRP-2026Q2-01")
    categoria: Categoria
    canal: Canal
    pct: float = Porcentaje


class GrillaExtraida(BaseModel):
    """Filas de un grid comercial."""
    filas: list[FilaGrilla] = Field(min_length=1)


class CampanaExtraida(_ConVigencia):
    """Condición de una campaña de descuento."""
    canal: Canal
    cantidad_min: Optional[int] = Field(default=None, ge=1,
                                        description="Unidades mínimas por línea; null si aplica a toda la venta")
    pct: float = Porcentaje


class Tramo(BaseModel):
    cumplimiento_min: float = Field(ge=0.5, le=1.5, description="Fracción del objetivo: 90 % es 0.90")
    pct: float = Porcentaje


class CartaRebateExtraida(_ConVigencia):
    """Condiciones de una carta comercial de rebate."""
    cliente_id: str = Field(pattern=r"^CLI-[A-Z]{3}-\d{3}$")
    objetivo_trimestral: int = Field(gt=0, description="Unidades por trimestre")
    tramos: list[Tramo] = Field(min_length=1)


class Excepcion(BaseModel):
    cliente_id: str = Field(pattern=r"^CLI-[A-Z]{3}-\d{3}$")
    estado: Literal["aprobada", "rechazada"]
    concepto: Literal["dscto_comercial"] = "dscto_comercial"
    tope_pct: Optional[float] = Field(default=None, ge=0, le=0.30,
                                      description="Tope aprobado o solicitado, como fracción")
    desde: Optional[date] = None
    hasta: Optional[date] = None


class ActaExtraida(BaseModel):
    """Excepciones a la política aprobadas o rechazadas en el acta."""
    excepciones: list[Excepcion] = Field(default_factory=list)


ESQUEMA_POR_TIPO = {
    "politica": PoliticaExtraida,
    "grilla": GrillaExtraida,
    "campana": CampanaExtraida,
    "carta_rebate": CartaRebateExtraida,
    "acta": ActaExtraida,
}
