@{
    # AutoDL 控制台 SSH 登录说明中的主机名和端口（不要填写网页地址）
    SshHostName = "region-1.autodl.com"
    SshPort = 12345
    SshUser = "root"

    # 推荐使用私钥。留空字符串时使用 SSH 默认密钥或 SSH Agent。
    IdentityFile = "C:\Users\<user>\.ssh\id_ed25519"

    RemoteProjectRoot = "/root/autodl-tmp/minicpmv45-service"
    BaseModelRemotePath = "/root/autodl-tmp/MiniCPM-V-4_5"
    AdapterRemotePath = "/root/autodl-tmp/checkpoint-600"

    LocalBaseModelPath = "E:\dachuang\MiniCPM-V-4_5"
    LocalAdapterPath = "E:\dachuang\minicpmv45_scene4_deployment\lora_adapter\checkpoint-600"

    LocalPort = 18080
    RemoteServicePort = 18080
    BackendBaseUrl = "http://127.0.0.1:8000"

    # 可选：用于真实 GPU 单窗口验收
    SmokeVideoPath = "E:\dachuang\SAV\dataset\20181016_05_1064.mp4"
}
