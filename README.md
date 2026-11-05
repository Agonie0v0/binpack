# binpack

把 Linux 二进制文件打包成 NAS 可用的 Docker 镜像。

自动识别架构和基础环境，输出镜像包、Compose 与 SHA256 校验文件；支持一键导入飞牛本机镜像库、账号登录和历史缓存清理。

![工作台](design/workbench-desktop.png)

## 部署

在飞牛 Docker 中创建 Compose 项目，粘贴以下配置。镜像支持 amd64 / arm64。

```yaml
services:
  binpack:
    container_name: binpack
    image: ghcr.io/agonie0v0/binpack:latest
    ports:
      - "38627:8088"
    environment:
      DATA_DIR: /data
      COOKIE_SECURE: "0"
    volumes:
      - binpack-data:/data
      - /var/run/docker.sock:/var/run/docker.sock
    restart: unless-stopped

volumes:
  binpack-data:
```

访问 `http://NAS的IP:38627`，从容器日志中的 `FIRST SETUP TOKEN` 获取初始化凭证，创建管理员账号。没有默认密码。容器名和左侧端口可自行修改。

Docker Socket 挂载用于构建和导入镜像，具有宿主机 Docker 管理权限，请仅供可信管理员使用。旧版本升级需同时补上这项挂载并重建容器。

## 使用

1. 上传 Linux ELF 文件，填写镜像名称和标签。
2. 核对识别结果，按需调整高级设置，选择是否“完成后导入飞牛”。
3. 生成后下载镜像包与部署配置，或直接在飞牛镜像库中使用。

端口和数据目录仅在帮助信息明确声明默认值时自动填写；启动参数留空沿用程序默认行为，手动输入会保留。导入镜像不会自动启动容器，同名标签会更新。

目前支持单个 amd64 / arm64 可执行文件，最大 256 MB。首次构建需联网获取基础镜像；依赖额外资源或特殊动态库的程序需自行准备。跨架构打包会跳过运行帮助信息的分析。

## 数据与更新

数据保存在 `binpack-data` 卷：上传文件位于 `/data/uploads`，历史和镜像包位于 `/data/jobs`，账号位于 `/data/auth.sqlite3`。默认缓存上限 10 GB，可在网页清理，清理不会删除账号或已导入的镜像。

更新时拉取 `latest` 并重建容器，**保留原数据卷**。使用命令行时执行：

```sh
docker compose pull
docker compose up -d
```

<details>
<summary>Lucky HTTPS 反代与密码重置</summary>

Lucky 后端使用 `http://NAS的IP:38627`，保留 Host。在 Compose 的 `environment` 中设置以下两项，重新部署后通过 HTTPS 域名访问：

```yaml
COOKIE_SECURE: "1"
PUBLIC_ORIGIN: https://你的工具域名
```

`PUBLIC_ORIGIN` 填写实际访问源地址，包含非标准端口（如有），不带路径。

忘记密码时，在容器终端执行，按提示输入新密码：

```sh
python /opt/image-packager/server.py --data-dir /data --reset-password
```

</details>

[Compose 文件](compose.yaml) · [自动构建与发布](https://github.com/Agonie0v0/binpack/actions/workflows/image.yml)
