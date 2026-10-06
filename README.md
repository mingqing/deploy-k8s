# deploy-k8s

k8s生态组件过多，对新人入门并不友好，本项目在于结合当前生产集群维护经验，总结一套标准的部署模版，接入内部gitlab ci实现集群基础设施的自动化管理，同时也会不断迭代优化，以实现快速搭建一套生产可用的环境。

## 快速开始

请访问 [OPSaid](https://opsaid.cn/docs/deploy-k8s/quickstart/) 文档，并快速开始你的测试。

## ARM64 与 Kubernetes 1.36

新建集群基线为 Kubernetes v1.36.5 + containerd 2.x + Cilium，支持按版本/架构准备 amd64 与 arm64 二进制。Mac mini M2 + Fedora Asahi 是首个 ARM64 验证目标，实机验收尚未完成；组件只维护一个主方案，旧 profile 不承诺持续兼容或安全维护。

部署步骤、边界与验收见 [ARM64 / Kubernetes 1.36](docs/arm64-kubernetes-1.36.md)。本项目的版本配置更新不等于支持从 1.26 跨版本直接升级。
