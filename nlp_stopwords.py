"""Stopwords para análisis de comentarios en español, portugués e inglés."""

from __future__ import annotations

# Listas compactas pero suficientes para comentarios de Instagram (ES + PT + EN).
_STOPWORDS_ES = """
a al algo algunos alguna algunas ante aquel aquella aquellas aquello aquellos aqui arriba atras
bajo bien cada como con contra cual cuales cualquier cualquiera cuando de del desde donde dos el
ella ellas ellos en entre era eramos eran eras es esa esas ese eso esos esta estaba estaban
estado estados estamos estan estar estara estaran estaras estare estaria estarian estarias esto
estos estoy fin fue fuera fueron fui fuimos ha haber habia habian habra habran haya hayan he
hemos hizo hubiera hubieran hubo incluso ir ja la las le les lo los mas me mi mia mias mio mios
mis mucho muchos muy nada ni no nos nosotras nosotros nuestra nuestras nuestro nuestros o os otra
otras otro otros para pero poco por porque que quien quienes se sea sean ser sera seran si sido
siendo sin sobre so solamente solo somos son soy su sus suya suyas suyo suyos tambien tan tanto
te ti tiene tienen todo todos tu tus tuya tuyas tuyo tuyos un una uno unos usted ustedes ya yo
""".split()

_STOPWORDS_PT = """
ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de dela delas dele deles depois
dessa dessas desse desses desta destas deste destes disso disto do dos e ela elas ele eles em
entre era eram essa essas esse esses esta estao estas este estes eu ha isso isto ja lhe lhes lo
mais mas me mesma mesmas mesmo mesmos meu meus minha minhas muito na nas nao nos nossa nossas
nosso nossos o os ou para pela pelas pelo pelos por qual quando que quem se sem ser sua suas
tambem te tem temos tens ter sua suas teu teus tu tus um uma uns umas voce voces vos
""".split()

_STOPWORDS_EN = """
a an and are as at be been being but by can could did do does doing done for from had has have
having he her here hers herself him himself his how i if in into is it its itself just me more
most my myself no nor not of off on once only or other our ours ourselves out over own same she
should so some such than that the their theirs them themselves then there these they this those
through to too under until up very was we were what when where which while who whom why will with
would you your yours yourself yourselves
""".split()

# Ruido típico de comentarios en redes (no aportan a narrativas).
_STOPWORDS_SOCIAL = """
http https www com instagram post reel story send please great shot really amazing love nice
good best wow omg yes yeah yea ok okay hey hi hello thanks thank gracias obrigado parabens
felicidades felicidade abrazo besos saludos cordiales bendiga dios amigo amiga bro
""".split()

# Palabras frecuentes que aún colaban en top_terms.
_STOPWORDS_EXTRA = """
hay ahi alla aja eh uh um mas muy tan bien solo cada donde cuando como hasta ojala
ver hacer hace ahora siempre todas todos nunca puede personas parte lugar
""".split()

STOPWORDS: frozenset[str] = frozenset(
    w.lower()
    for w in (_STOPWORDS_ES + _STOPWORDS_PT + _STOPWORDS_EN + _STOPWORDS_SOCIAL + _STOPWORDS_EXTRA)
    if len(w) > 1
)

STOPWORDS_BY_LANG: dict[str, frozenset[str]] = {
    "es": frozenset(
        w.lower()
        for w in (_STOPWORDS_ES + _STOPWORDS_SOCIAL + _STOPWORDS_EXTRA)
        if len(w) > 1
    ),
    "pt": frozenset(
        w.lower()
        for w in (_STOPWORDS_PT + _STOPWORDS_SOCIAL + _STOPWORDS_EXTRA)
        if len(w) > 1
    ),
    "en": frozenset(
        w.lower()
        for w in (_STOPWORDS_EN + _STOPWORDS_SOCIAL + _STOPWORDS_EXTRA)
        if len(w) > 1
    ),
}


def get_stopwords(language: str = "") -> frozenset[str]:
    code = (language or "").lower().split("-")[0]
    if code in STOPWORDS_BY_LANG:
        return STOPWORDS_BY_LANG[code]
    return STOPWORDS
