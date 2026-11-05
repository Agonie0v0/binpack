# binpack

面向 NAS 的通用二进制镜像打包工作台。

**当前为预览版：账号初始化、登录、退出和密码修改已实现；二进制打包、镜像归档下载、历史缓存清理和自动导入 Docker 仍未实现。** 文件选择和 ELF 架构识别在浏览器本地完成，演示不会上传或执行二进制。发布的容器用于体验界面和账号系统。

## 飞牛 / NAS 部署

公开镜像：`ghcr.io/agonie0v0/binpack:latest`，支持 `linux/amd64` 和 `linux/arm64`。`latest` 指主分支最近通过检查的版本，当前功能仍处于预览阶段。服务镜像架构与未来上传文件的运行架构是两回事。

在飞牛 Docker 的 Compose 项目中粘贴：

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
    restart: unless-stopped

volumes:
  binpack-data:
```

访问 `http://NAS的IP:38627`。从容器日志中的 `FIRST SETUP TOKEN` 取得一次性初始化凭证，设置自己的管理员账号。没有默认密码。更新时重新拉取镜像并重建容器，保留数据卷；命令行为 `docker compose pull && docker compose up -d`。

`container_name: binpack` 固定容器显示名称，可以改成自己的名字。同一 NAS 上的容器名称必须唯一；修改后重新部署 Compose 项目即可生效。

`binpack-data` 是 NAS Docker 管理的数据卷，实际位置可用 `docker volume inspect <项目名>_binpack-data` 查看。也可以改为 `/vol1/1000/docker/binpack/data:/data` 这样的专用绑定目录，路径按实际 NAS 修改。启动器会将数据目录及已有账号文件的所有者设为 `10001:10001`，目录权限设为 `700`、账号文件设为 `600`，然后以普通用户运行服务。它不会递归修改目录内其他文件。账号数据库不能作为缓存清理。当前版本尚不产生打包缓存。

容器入口以 root 准备数据目录，随后移除附加组并切换为 UID/GID `10001:10001` 运行服务，无需特权模式或 Docker Socket。如果手动设置 Compose 的 `user: "10001:10001"`，则跳过自动权限修复，需要提前赋予目录和账号文件的读写权限。环境变量 `PORT` 可修改容器监听端口，端口映射需同步修改。

若日志出现 `unable to open database file` 或 `Cannot prepare data directory`，请重新拉取最新镜像并重建容器，保留原数据卷。目录必须可写，磁盘需要有剩余空间；只读挂载或 NAS ACL 拒绝访问时需要在 NAS 上调整。不要删除账号数据库或数据卷来修复权限。

源码内的 [compose.yaml](compose.yaml) 可直接用于 NAS 部署：`docker compose up -d`。如需从源码构建，执行 `docker build -t binpack:local .`。

## 自动发布

[GitHub Actions](https://github.com/Agonie0v0/binpack/actions/workflows/image.yml) 会在测试通过后发布到 GHCR：

- 推送 `main`：更新 `latest` 和 `preview`，同时保留 `sha-<短提交号>` 镜像。
- 推送 `v*` 标签：发布同名标签，例如 `v0.1.0-preview.1`；`latest` 始终跟随主分支。
- Actions 页面手动运行：发布所选分支的提交标签；选择 `main` 时也更新 `latest` 和 `preview`。
- Pull Request：执行测试与容器运行检查，不发布镜像。

流程使用 GitHub 内置的 `GITHUB_TOKEN`，无需配置 Docker Hub 密码。Actions 依赖固定到提交 SHA，Dependabot 每月检查更新。发布检查包括服务端鉴权测试、前端逻辑测试、容器内重复鉴权测试、启动健康检查、未登录拦截，以及 NAS 数据目录权限修复、账号保留、重启和只读挂载诊断；不代表已验证实际二进制打包功能。

需要离线导入 NAS 时，在能拉取 GHCR 的 Docker 主机执行（ARM NAS 改为 `linux/arm64`）：

```sh
docker pull --platform linux/amd64 ghcr.io/agonie0v0/binpack:latest
docker save -o binpack-latest-amd64.tar ghcr.io/agonie0v0/binpack:latest
```

将生成的 tar 文件导入飞牛 Docker 镜像。此处导出的是工具本身的预览镜像。

## 本地运行

使用 Python 3.13 或更高版本，无第三方 Python 依赖：

```sh
python server.py --host 0.0.0.0 --port 8088 --data-dir ./data
```

NAS 容器版把 `DATA_DIR` 设置为 `/data`，并挂载到 NAS 的持久化目录。

第一次打开网页会进入设置管理员页面。从服务启动日志的 `FIRST SETUP TOKEN` 取得一次性初始化凭证，设置自己的账号与密码；没有默认账号密码。初始化完成后，凭证文件自动删除，不能再次创建管理员覆盖原账号。

账号支持 3–32 位英文字母、数字及 `. _ -`，首位为字母或数字。密码支持 12–128 个字符。

## 登录与退出

- 工作台、账号页、未来的 API 与下载路由均在服务端鉴权。未登录时页面跳转登录页，接口返回 401。
- 密码使用独立随机盐和 PBKDF2-HMAC-SHA256（600,000 次），不保存明文密码。
- 会话令牌仅通过 HttpOnly、SameSite=Strict Cookie 传递，数据库中也只保存令牌摘要，不使用浏览器 localStorage 保存登录凭证。
- 普通登录浏览器会话有效，服务端最长 24 小时，空闲 8 小时失效。“保持登录 7 天”最长 7 天，空闲 24 小时失效。浏览器的会话恢复行为因浏览器而异，应使用退出按钮主动结束会话。
- 退出使当前会话立即失效；修改或终端重置密码会撤销所有设备的会话。
- 每个直接连接来源在 10 分钟内累计 10 次失败后暂缓 60 秒，成功验证会清零。应用不信任用户可伪造的转发 IP；使用 Lucky 后同一反代的用户共享该限制。
- 写操作校验同源 Origin 与 CSRF 凭证；账号与令牌文件不会由网页服务器提供下载。

密码与会话设计参考：[OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。

## 数据位置与缓存清理边界

账号和会话保存在数据目录中的 `auth.sqlite3`。首次设置前还有私有文件 `setup-token`。后续打包历史与镜像归档使用独立子目录，**清理打包缓存不能删除账号数据库**。

开发预览使用 `.preview-auth/`，该目录已加入忽略列表，不能随源码或最终镜像分发。

## Lucky 反向代理

工具本身提供 HTTP。由 Lucky 提供外部 HTTPS，转发到工具的 HTTP 端口。部署时设置：

```yaml
environment:
  DATA_DIR: /data
  COOKIE_SECURE: "1"
  PUBLIC_ORIGIN: https://你的工具域名
```

反代保留客户端 Host；`PUBLIC_ORIGIN` 必须是浏览器实际访问的完整源地址，包含非标准端口（如有），不带路径。设置 `COOKIE_SECURE=1` 后通过 HTTPS 访问；直接用 HTTP 登录时浏览器不会发送 Secure Cookie。

第一版使用一个管理员账号，与飞牛系统账号独立，不包含开放注册、邮件找回或多人权限分级。

## 忘记密码

在飞牛容器终端执行：

```sh
python /opt/image-packager/server.py --data-dir /data --reset-password
```

终端会隐藏输入并要求确认新密码，不通过网页或命令行参数传递明文密码。账号数据库不存在时，应按首次初始化流程设置账号。

## 验证

```sh
python -m unittest -v test_auth.py
node design/verify-preview.mjs
node design/verify-auth-client.mjs
```

鉴权检查覆盖：未登录页面与接口拦截、初始化凭证、并发初始化、密码和令牌不以明文持久化、Cookie 标志、CSRF 与 Origin、非法请求、退出、密码修改撤销所有会话、会话超时、重启保留和失败限流。飞牛部署仍需实机验证。

## 界面

![登录页](design/login-desktop.jpg)

![工作台界面预览](design/redesign-desktop.png)
