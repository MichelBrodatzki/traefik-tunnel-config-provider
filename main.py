import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

import yaml

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('KubeTunnelConfigCollector')

app = FastAPI()
try:
    # Running inside the cluster: use the mounted ServiceAccount token.
    config.load_incluster_config()
    api_client = client.ApiClient()
except config.ConfigException:
    # Local development: fall back to kubeconfig.
    config.load_kube_config()
    active_context = config.list_kube_config_contexts()[1]
    api_client = config.new_client_from_config(context=active_context.get('name'))

v1 = client.CoreV1Api(api_client=api_client)
custom = client.CustomObjectsApi(api_client=api_client)


@app.get('/health')
async def health():
    return {'running': True}

@app.get('/api/traefik')
async def get_traefik_config() -> Response:
    try:
        gateways = custom.list_custom_object_for_all_namespaces(
            'gateway.networking.k8s.io',
            'v1',
            'gateways'
        )
    except ApiException as exc:
        # API server reachable but rejected us (e.g. RBAC, CRD missing).
        log.error(
            'Kubernetes API rejected the Gateway list (status %s): %s',
            exc.status,
            exc.reason
        )
        raise HTTPException(
            status_code=503,
            detail='Unable to query the Kubernetes API for Gateways.'
        )
    except Exception:
        # Connectivity / unexpected failures: log the trace, don't leak it.
        log.exception('Unexpected error while listing Gateways.')
        raise HTTPException(
            status_code=503,
            detail='Unable to query the Kubernetes API for Gateways.'
        )

    config = {
        'http': {
            'routers': {},
            'services': {}
        }
    }

    for gateway in gateways.get('items'):
        gw_name = gateway.get('metadata', {}).get('name')
        if gw_name is None:
            log.warning('Found Gateway without name. Skipping ...')
            continue

        ressource_annotations = gateway.get('metadata', {}).get('annotations') or {}
        public_tunnel_enable = ressource_annotations.get('brodatzki.net/enable-public-tunnel') == 'true'
        public_tunnel_additional_rule = ressource_annotations.get('brodatzki.net/add-public-tunnel-rule')
        auth_tunnel_enable = ressource_annotations.get('brodatzki.net/enable-authorized-tunnel') == 'true'
        auth_tunnel_additional_rule = ressource_annotations.get('brodatzki.net/add-authorized-tunnel-rule')

        if not public_tunnel_enable and not auth_tunnel_enable:
            log.info(
                'Gateway %s has not enabled tunneling. Skipping ...',
                gw_name
            )
            continue

        if (
            public_tunnel_enable and auth_tunnel_enable
            and public_tunnel_additional_rule == auth_tunnel_additional_rule
        ):
            log.warning(
                'Gateway %s enabled public and auth tunneling, but both rulesets are equivalent. Defaulting to only auth tunnel.',
                gw_name
            )
            public_tunnel_enable = False

        hostname = [
            listener.get('hostname')
            for listener in gateway.get('spec', {}).get('listeners') or []
            if listener.get('protocol') == 'HTTPS'
        ]
        if len(hostname) == 0:
            log.warning(
                'Gateway %s has no HTTPS listener. Skipping ...',
                gw_name
            )
            continue
        hostname = hostname[0]

        if public_tunnel_enable:
            public_tunnel_router_rules = [
                f'Host(`{hostname}`)'
            ]
            if public_tunnel_additional_rule:
                public_tunnel_router_rules.append(
                    public_tunnel_additional_rule
                )

            config['http']['routers'][f'to-{gw_name}-public'] = {
                'rule': ' && '.join(public_tunnel_router_rules),
                'tls': {
                    'certResolver': 'letsencrypt'
                },
                'service': gw_name,
                'priority': 1
            }

        if auth_tunnel_enable:
            auth_tunnel_router_rules = [
                f'Host(`{hostname}`)'
            ]
            if auth_tunnel_additional_rule:
                auth_tunnel_router_rules.append(
                    auth_tunnel_additional_rule
                )

            config['http']['routers'][f'to-{gw_name}-authorized'] = {
                'rule': ' && '.join(auth_tunnel_router_rules),
                'tls': {
                    'certResolver': 'letsencrypt'
                },
                'middlewares': ['oidc-ka1'],
                'service': gw_name,
                'priority': 2
            }

        config['http']['services'][gw_name] = {
            'loadBalancer': {
                'servers': [
                    {'url': f'https://{hostname}'}
                ]
            }
        }

    return Response(yaml.safe_dump(config), 200, media_type='application/yaml')
