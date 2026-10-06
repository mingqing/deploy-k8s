"""Render real configuration templates for both architectures; no node changes."""
import json
import unittest
import tomllib
from pathlib import Path
import yaml
from jinja2 import Environment, StrictUndefined
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined)
ENV.filters['to_json'] = json.dumps
ENV.filters['bool'] = lambda v: str(v).lower() in ('true','1')
ENV.tests['version'] = lambda value, other, op: Version(value.lstrip('v')) >= Version(other.lstrip('v'))


def context(arch):
    v = {}
    for file in ['all.yaml', 'default.yaml', 'component-v1.36.yaml']:
        v.update(yaml.safe_load((ROOT/'ansible/group_vars'/file).read_text()))
    v.update(ansible_architecture=arch, ansible_selinux={'status': 'enabled'},
             inventory_hostname='m2', groups={'kube_control_plane': ['m2'], 'etcd': ['m2']},
             hostvars={'m2': {'ip': '192.0.2.10'}})
    def render(value):
        if isinstance(value, str) and ('{{' in value or '{%' in value):
            return ENV.from_string(value).render(**v)
        if isinstance(value, dict): return {k:render(a) for k,a in value.items()}
        if isinstance(value, list): return [render(a) for a in value]
        return value
    for _ in range(8): v = {k:render(a) for k,a in v.items()}
    return v


def template(path, variables):
    return ENV.from_string((ROOT/'ansible/roles'/path).read_text()).render(**variables)


class ModernProfile(unittest.TestCase):
    def test_real_templates_on_both_architectures(self):
        for host_arch, target in [('aarch64', 'arm64'), ('x86_64', 'amd64')]:
            with self.subTest(architecture=target):
                v = context(host_arch)
                self.assertEqual(v['server_arch'], target)
                config = tomllib.loads(template('runtime/templates/containerd/config-v3.toml.j2', v))
                self.assertEqual(config['version'], 3)
                self.assertTrue(config['plugins']['io.containerd.cri.v1.runtime']['containerd']['runtimes']['runc']['options']['SystemdCgroup'])
                kubeadm = list(yaml.safe_load_all(template('control/templates/kubeadm/config-v1beta4.yaml.j2', v)))
                cluster = next(d for d in kubeadm if d['kind'] == 'ClusterConfiguration')
                self.assertEqual(cluster['apiVersion'], 'kubeadm.k8s.io/v1beta4')
                for component in ['apiServer','controllerManager','scheduler']:
                    self.assertIsInstance(cluster[component]['extraArgs'], list)
                    self.assertTrue(all(set(a) == {'name', 'value'} for a in cluster[component]['extraArgs']))
                self.assertIsInstance(cluster['etcd']['local']['extraArgs'], list)
                for name in ['etcd','kube-apiserver','kube-controller-manager','kube-scheduler']:
                    pod = yaml.safe_load(template('control/templates/manifests/'+name+'.yaml.j2',v))
                    self.assertNotIn('--enable-v2=true',pod['spec']['containers'][0]['command'])
                    self.assertNotIn('--feature-gates=WindowsHostNetwork=false',pod['spec']['containers'][0]['command'])
                flags = template('node/templates/kubelet/kubeadm-flags.env.j2',v)
                self.assertNotIn('--container-runtime=remote',flags)
                k = yaml.safe_load(template('node/templates/kubelet/config.yaml.j2',v))
                self.assertEqual(k['cgroupDriver'],'systemd')
                self.assertNotIn('kubeletCgroups',k)
                cilium = yaml.safe_load(template('control/templates/addons/cilium/values-modern.yaml.j2',v))
                self.assertNotIn('://', cilium['k8sServiceHost'])
                self.assertTrue(cilium['kubeProxyReplacement'])
                self.assertFalse(cilium['envoy']['enabled'])
                for path in ['kustomization.yaml', 'cluster/roles.yaml', 'config/configmap/Corefile', 'service/services.yaml', 'workloads/deployment.yaml']:
                    result = template('control/templates/addons/coredns/'+path+'.j2',v)
                    if path != 'config/configmap/Corefile': list(yaml.safe_load_all(result))

    def test_downloads_are_isolated_and_checked(self):
        source = (ROOT/'ansible/roles/binary/tasks/modern_arch.yaml').read_text()
        for arch in ['amd64','arm64']:
            v = context('aarch64'); v['download_arch']=arch
            tasks = yaml.safe_load(source)
            paths=[]
            for task in tasks:
                if 'ansible.builtin.get_url' not in task: continue
                params=task['ansible.builtin.get_url']
                for raw_item in task['loop']:
                    item = {k: ENV.from_string(str(a)).render(**v) for k,a in raw_item.items()} if isinstance(raw_item, dict) else raw_item
                    p={k:ENV.from_string(str(a)).render(item=item,**v) for k,a in params.items()}
                    self.assertIn('/'+arch+'/',p['dest'])
                    self.assertTrue(p['checksum'].startswith('sha256:https://'))
                    paths.append(p['dest'])
            self.assertEqual(len(paths),len(set(paths)))
            self.assertEqual(len(paths),9)

    def test_task_yaml(self):
        for path in (ROOT/'ansible').rglob('*.yaml'):
            if 'templates' not in path.parts: list(yaml.safe_load_all(path.read_text()))


if __name__ == '__main__': unittest.main()
