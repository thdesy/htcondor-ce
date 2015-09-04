
import os
import re
import json
import time
import types
import xml.sax.saxutils
import wsgiref.util

import genshi.template

import classad
htcondor = None

import htcondor_ce.rrd

_initialized = None
_loader = None
_view = None


def check_initialized(environ):
    global _initialized
    global _loader
    global _cp
    global htcondor
    if not _initialized:
        if 'htcondorce.templates' in environ:
            _loader = genshi.template.TemplateLoader(environ['htcondorce.templates'], auto_reload=True)
        else:
            _loader = genshi.template.TemplateLoader('/usr/share/condor-ce/templates', auto_reload=True)
        ce_config = environ.get('htcondorce.config', '/etc/condor-ce/condor_config')
        _check_htcondor()
        _initialized = True


def _check_htcondor():
    global _initialized
    global htcondor
    if not _initialized and not htcondor:
        os.environ.setdefault('CONDOR_CONFIG', "/etc/condor-ce/condor_config")
        htcondor = __import__("htcondor")


def _get_pool(environ):
    environ_pool = None
    if environ and 'htcondorce.pool' in environ:
        environ_pool = environ['htcondorce.pool']
    if environ_pool:
        return environ_pool
    _check_htcondor()
    if not htcondor:
        return None

    return htcondor.param.get("HTCONDORCE_WEBAPP_POOL")


def _get_name(environ):
    environ_name = None
    if environ and 'htcondorce.name' in environ:
        environ_name = environ['htcondorce.name']
    if environ_name:
        return environ_name
    _check_htcondor()
    if not htcondor:
        return _get_pool(environ)

    config_name = htcondor.param.get("HTCONDORCE_WEBAPP_NAME")
    if not config_name:
        return _get_pool(environ)


def get_schedd_obj(environ=None):
    pool = _get_pool(environ)
    if pool:
        coll = htcondor.Collector(pool)
        name = _get_name(environ)
        return htcondor.Schedd(coll.locate(htcondor.DaemonTypes.Schedd, name))
    return htcondor.Schedd()


def get_schedd_ad(environ):
    pool = _get_pool(environ)
    coll = htcondor.Collector(pool)
    name = _get_name(environ)
    if name:
        return coll.query(htcondor.AdTypes.Schedd, "Name=?=%s" % classad.quote(name))[0]
    return coll.locate(htcondor.AdTypes.Schedd)[0]


def get_spooldir():
    _check_htcondor()
    spooldir = htcondor.param.get("HTCONDORCE_WEBAPP_SPOOL")
    if not spooldir:
        if not os.path.exists("tmp"):
            os.mkdir("tmp")
        spooldir = "tmp"
    return spooldir


def ad_to_json(ad):
    result = {}
    for key in ad:
        val_expr = ad.lookup(key)
        if classad.ExprTree("%s =?= UNDEFINED" % key).eval(ad):
            result[key] = {"_condor_type": "expr", "expr": val_expr.__repr__()}
        else:
            val = val_expr.eval()
            if isinstance(val, types.ListType) or isinstance(val, types.DictType):
                result[key] = {"_condor_type": "expr", "expr": val_expr.__repr__()}
            else:
                result[key] = val
    return result


def schedd(environ, start_response):
    ad = get_schedd_ad(environ)
    result = ad_to_json(ad)

    status = '200 OK'
    headers = [('Content-type', 'application/json'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    return [ json.dumps(result) ]


def totals(environ, start_response):
    schedd = get_schedd_obj(environ)
    results = {"Running": 0, "Idle": 0, "Held": 0, "UpdateDate": time.time()}
    for job in schedd.xquery("true", ["JobStatus"]):
        if job.get("JobStatus") == 1:
            results['Idle'] += 1
        elif job.get("JobStatus") == 2:
            results['Running'] += 1
        elif job.get("JobStatus") == 5:
            results['Held'] += 1

    status = '200 OK'
    headers = [('Content-type', 'application/json'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    return [ json.dumps(results) ]


def pilots(environ, start_response):
    schedd = get_schedd_obj(environ)
    job_count = {}
    for job in schedd.xquery('true', ['x509UserProxyVOName', 'x509UserProxyFirstFQAN', 'JobStatus', 'x509userproxysubject']):
        DN = job.get("x509userproxysubject", 'Unknown')
        VO = job.get('x509UserProxyVOName', 'Unknown')
        VOMS = job.get('x509UserProxyFirstFQAN', '').replace("/Capability=NULL", "").replace("/Role=NULL", "")
        job_key = (DN, VO, VOMS)
        if job_key not in job_count:
            job_count[job_key] = {"Running": 0, "Idle": 0, "Held": 0, "Jobs": 0, "DN": DN, "VO": VO, "VOMS": VOMS}
        results = job_count[job_key];
        results["Jobs"] += 1
        if job.get("JobStatus") == 1:
            results['Idle'] += 1
        elif job.get("JobStatus") == 2:
            results['Running'] += 1
        elif job.get("JobStatus") == 5:
            results['Held'] += 1

    status = '200 OK'
    headers = [('Content-type', 'application/json'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    return [ json.dumps(job_count.values()) ]


def vos_json(environ, start_response):
    schedd = get_schedd_obj(environ)
    job_count = {}
    for job in schedd.xquery('true', ['x509UserProxyVOName', 'JobStatus']):
        VO = job.get('x509UserProxyVOName', 'Unknown')
        job_key = VO
        if job_key not in job_count:
            job_count[job_key] = {"Running": 0, "Idle": 0, "Held": 0, "Jobs": 0}
        results = job_count[job_key];
        results["Jobs"] += 1
        if job.get("JobStatus") == 1:
            results['Idle'] += 1
        elif job.get("JobStatus") == 2:
            results['Running'] += 1
        elif job.get("JobStatus") == 5:
            results['Held'] += 1

    status = '200 OK'
    headers = [('Content-type', 'application/json'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    return [ json.dumps(job_count) ]


def vos(environ, start_response):
    vos = htcondor_ce.rrd.list_vos(environ)

    status = '200 OK'
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    tmpl = _loader.load('vos.html')

    info = {
        'vos': vos,
    }

    return [tmpl.generate(**info).render('html', doctype='html')]


def metrics(environ, start_response):

    metrics = htcondor_ce.rrd.list_metrics(environ)

    status = '200 OK'
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    tmpl = _loader.load('metrics.html')

    info = {
        'metrics': metrics,
    }

    return [tmpl.generate(**info).render('html', doctype='html')]


def index(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    tmpl = _loader.load('index.html')

    info = {
        'version': htcondor.version(),
        'ceversion': str(classad.ExprTree(htcondor.param.get("HTCondorCEVersion", '"Unknown"')).eval()),
        'resource': str(classad.ExprTree(htcondor.param.get("OSG_Resource", '"Unknown"')).eval()),
        'resourcegroup': str(classad.ExprTree(htcondor.param.get("OSG_ResourceGroup", '"Unknown"')).eval()),
        'batchsys': str(classad.ExprTree(htcondor.param.get("OSG_BatchSystems", '"Unknown"')).eval()),
    }

    return [tmpl.generate(**info).render('html', doctype='html')]


ce_graph_re = re.compile(r'^/+graphs/+ce/?([a-zA-Z]+)?/?$')
def ce_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = ce_graph_re.match(path)
    interval = "daily"
    if m.groups()[0]:
        interval=m.groups()[0]

    return [ htcondor_ce.rrd.graph(environ, "jobs", interval) ]


vo_graph_re = re.compile(r'^/*graphs/+vos/+([a-zA-Z._]+)/?([a-zA-Z]+)?/?$')
def vo_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = vo_graph_re.match(path)
    interval = "daily"
    environ['vo'] = m.groups()[0]
    if m.groups()[1]:
        interval=m.groups()[1]

    return [ htcondor_ce.rrd.graph(environ, "vos", interval) ]


metrics_graph_re = re.compile(r'^/*graphs/+metrics/+([a-zA-Z._]+)/+([a-zA-Z._]+)/?([a-zA-Z]+)?/?$')
def metrics_graph(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'image/png'),
               ('Cache-Control', 'max-age=60, public')]
    start_response(status, headers)

    path = environ.get('PATH_INFO', '')
    m = metrics_graph_re.match(path)
    interval = "daily"
    environ['group'] = m.groups()[0]
    environ['name'] = m.groups()[1]
    if m.groups()[-1]:
        interval=m.groups()[-1]

    return [ htcondor_ce.rrd.graph(environ, "metrics", interval) ]


def not_found(environ, start_response):
    status = '404 Not Found'
    headers = [('Content-type', 'text/html'),
              ('Cache-Control', 'max-age=60, public'),
              ('Location', '/')]
    start_response(status, headers)
    path = environ.get('PATH_INFO', '').lstrip('/')
    return ["Resource %s not found" % xml.sax.saxutils.escape(path)]


urls = [
    (re.compile(r'^/*$'), index),
    (re.compile(r'^vos/*$'), vos),
    (re.compile(r'^metrics/*$'), metrics),
    (re.compile(r'^json/+totals$'), totals),
    (re.compile(r'^json/+pilots$'), pilots),
    (re.compile(r'^json/+schedd$'), schedd),
    (re.compile(r'^json/+vos$'), vos_json),
    (re.compile(r'^graphs/ce/?'), ce_graph),
    (vo_graph_re, vo_graph),
    (metrics_graph_re, metrics_graph),
]


def application(environ, start_response):

    check_initialized(environ)

    path = environ.get('PATH_INFO', '').lstrip('/')
    
    for regex, callback in urls:
        match = regex.match(path)
        if match:
            environ['htcondorce.url_args'] = match.groups()
            return callback(environ, start_response)
    return not_found(environ, start_response)


