# ARM64 / Kubernetes 1.36 实验基线

状态：实现与静态验收；Mac mini M2 实机验收尚未完成。用于**新建集群**，不执行已有集群跨版本升级。

## 固定技术路线

- Kubernetes v1.36.5，containerd 2.2.8 + runc v1.5.2；cgroup v2 + systemd。
- 网络只维护 Cilium v1.20.2；用官方 chart 安装，不复用旧版手写 Cilium 清单。先验证 VXLAN 数据面；L7/Envoy、Hubble、Gateway API 在后续验证后接入，同一组件体系内扩展。
- CoreDNS v1.14.2；etcd 3.6.8-0、pause 3.10.2 对齐 Kubernetes v1.36.5 kubeadm 常量。
- amd64/arm64 共用配置，按目标架构分发；缓存路径包含版本和架构，下载验证官方 SHA256。
- 直接拉官方 OCI 多架构镜像，基础安装不依赖 Docker、gcc、单架构 rebuild/push。私有镜像站应保留完整 OCI index；本 PR 不自动向私有 registry 写入。
- 不启用 Calico、Kata、kube-proxy、Ingress NGINX，也不捆绑 Argo、监控、存储系统。旧 profile 仅保留给已有环境参考，不能视为仍在安全维护。

## Fedora Asahi 准备

保留 macOS；先完成 Asahi 系统安装、更新、固定 LAN IP、SSH。使用 Fedora Asahi 的原生内核，不由本脚本改引导器或格式化磁盘。

```bash
uname -m
uname -r
getconf PAGESIZE
stat -fc %T /sys/fs/cgroup
sudo bpftool feature probe kernel
```

`aarch64`、`cgroup2fs` 是必要检查；Asahi 内核可能使用 16KB 页，镜像是否包含 ARM64 **不等于**应用与 16KB 页兼容。预检查输出页大小，验收必须实际启动镜像并检查 Cilium agent 日志。额外核查 `CONFIG_BPF*`、`CONFIG_CGROUP_BPF`、BTF、overlayfs、br_netfilter。

Fedora 默认 zram：common 阶段关闭当前 swap，并写空 `zram-generator.conf` 禁用重启后的自动 swap。重启后以 `swapon --show` 验证。SELinux 保留主机配置并安装 container-selinux；若发生 AVC，先检查 `/data` 自定义目录标签及容器 bind mount 标签，不以关闭 SELinux 作为默认方案。

firewalld 由主机管理员配置：6443/TCP 供受信管理端/节点访问，2379–2380/TCP 仅 etcd 对等节点，10250/TCP 仅必要组件/管理源，8472/UDP 仅 Cilium VXLAN 节点间。单节点不必对 LAN 开放 etcd。业务 NodePort 按需开放，不能把 VXLAN 暴露到公网。

## 在 M2 本机执行

控制机使用 Linux 和本地连接，下载缓存与 Ansible 控制器在同一目录。远程混合集群也由这个 Linux 控制机分发；在 `binary_architectures` 中准备全部目标架构，每个目标可用 `host_vars` 显式指定 `server_arch`。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install 'ansible-core>=2.19,<2.20'
ansible-galaxy collection install -r ansible/requirements.yml
cd ansible
cp hosts_macmini_sample.ini hosts.ini
```

先修改 `hosts.ini` 中 `ip`，并在 `group_vars/all.yaml` 设置 cluster_name、cluster_domain、apiserver_haip（单机就是本机 LAN IP）、不冲突的 Pod/Service CIDR、随机 tls_bootstrap_token。示例 token 必须替换。M2 可用 `-e '{"binary_architectures":["arm64"]}'` 只下载 ARM64。

以下 `sudo` 保证本机任务和已有 PKI 角色具有所需权限；替换 `<venv-ansible-playbook>` 为虚拟环境中程序的绝对路径。

```bash
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --syntax-check
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --tags preflight
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --tags binary -e '{"binary_architectures":["arm64"]}'
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --tags pki
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --tags common
sudo <venv-ansible-playbook> -i hosts.ini deploy.yaml --tags control
```

预检查拒绝非 systemd、非 cgroup v2、不支持的组件选项、磁盘管理，以及不同版本的已安装 kubelet/containerd。不要全量无标签执行包含 uninstall 的 playbook。

在节点上：

```bash
sudo crictl ps -a
sudo kubectl get --raw=/readyz
sudo kubectl apply -k /etc/kubernetes/addons/kube-system
sudo kubectl get csr
# 核查节点名称、申请者和证书内容，只批准本次部署的节点 CSR。
sudo kubectl certificate approve <verified-node-csr>
sudo cilium install --version 1.20.2 --values /etc/kubernetes/addons/cilium/values.yaml
sudo cilium status --wait
sudo kubectl apply -k /etc/kubernetes/addons/coredns
sudo kubectl get nodes -L kubernetes.io/arch
```

不要将旧 quickstart 的 kubeadm v1beta3 文件或旧 Cilium kustomization 用于本 profile。v1beta4 文件作为配置参考生成；实际启动仍是本项目渲染 static Pod 和 kubelet，不会自动调用 kubeadm init/upgrade。

## 验收与可复现证据

- 四个控制平面容器 Running；`/readyz` 正常，节点 Ready、架构 arm64。
- 运行 ARM64/multi-arch 测试 Deployment；集群 DNS、ClusterIP、NodePort、NetworkPolicy 正常；执行 `cilium connectivity test`。
- 执行 `kubectl exec`、`kubectl logs`、端口转发；核查 kubelet RBAC 与 CSR 签发。
- 重启后 swap 保持关闭，containerd/kubelet 自动启动，Pod 恢复。
- 同版本重复执行结果可解释，无证书无故轮换；下载缓存没有旧版本/架构误复用。
- 加入 amd64 节点后重复网络测试，记录内核、page size、镜像 index/digest、组件版本与日志。
- 检查 SELinux AVC、etcd 数据权限、Cilium BPF 能力、磁盘空间和断电恢复。

没有完成这些实机检查前，不宣称 Fedora Asahi 或混合集群已获生产支持。已有 1.26 集群另行选择逐 minor 升级或新集群迁移。

## 来源

- [Kubernetes 1.36](https://kubernetes.io/releases/1.36/)
- [v1.36.5 kubeadm 常量](https://github.com/kubernetes/kubernetes/blob/v1.36.5/cmd/kubeadm/app/constants/constants.go)
- [Cilium Kubernetes 兼容范围](https://docs.cilium.io/en/stable/network/kubernetes/compatibility/)
- [containerd 2.x 配置](https://github.com/containerd/containerd/blob/release/2.2/docs/cri/config.md)
