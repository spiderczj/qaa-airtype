"""本机局域网 IP 枚举 —— 全程不碰 DNS/mDNS，避免 macOS 上把界面卡死。"""
import socket
import threading

def get_host_ip():
    """获取主要的本机 IP 地址"""
    ip = '127.0.0.1'
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        pass
    finally:
        if s is not None:
            s.close()
    return ip

def get_ifaddrs():
    """用 ioctl 直接读网卡 IPv4，不经过 DNS/mDNS，不会阻塞"""
    found = []
    try:
        import fcntl
        import struct as _struct

        # macOS 的 SIOCGIFADDR = _IOWR('i', 13, struct ifreq)
        SIOCGIFADDR = 0xC020690D
        # ifreq = 16 字节名字 + sockaddr；sockaddr_in 里 sin_addr 位于偏移 4，
        # 即整体偏移 20。
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _idx, name in socket.if_nameindex():
                try:
                    request = _struct.pack('32s', name.encode('utf-8')[:15])
                    response = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)
                    ip = socket.inet_ntoa(response[20:24])
                except OSError:
                    continue
                if ip not in ('127.0.0.1', '0.0.0.0') and ip not in found:
                    found.append(ip)
    except Exception as e:
        print(f"get_ifaddrs 失败: {e!r}")
    return found


def get_all_ips(timeout: float = 3.0):
    """获取所有可用的本机 IP 地址。

    优先走 ioctl 枚举网卡（无 DNS、无阻塞）；拿不到再退回 getaddrinfo，
    而 macOS 的 getaddrinfo 遇到 .local 主机名会走 mDNS 并长时间挂死，
    所以放进工作线程加超时；最后 UDP 探测兜底，保证总能拿到真实局域网 IP。
    """
    ips = []
    errors = []

    def resolve():
        try:
            hostname = socket.gethostname()
            for addr in socket.getaddrinfo(hostname, None):
                ip = addr[4][0]
                # 只保留 IPv4 地址，排除回环地址
                if ':' not in ip and ip not in ('127.0.0.1', '0.0.0.0') and ip not in ips:
                    ips.append(ip)
        except Exception as e:
            errors.append(f"getaddrinfo 失败: {e!r}")

    ifaddrs = get_ifaddrs()
    if ifaddrs:
        ips.extend(ifaddrs)
    else:
        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            print(f"get_all_ips: DNS 解析超过 {timeout}s 未返回，改用 UDP 探测")

    for message in errors:
        print(f"get_all_ips: {message}")

    # UDP 探测不依赖主机名解析，作为兜底保证总能拿到真实局域网 IP
    try:
        primary = get_host_ip()
        if primary and ':' not in primary and primary not in ('127.0.0.1', '0.0.0.0') and primary not in ips:
            ips.append(primary)
    except Exception as e:
        print(f"get_all_ips: get_host_ip 失败: {e!r}")

    # 如果没有找到任何 IP，添加默认值
    if not ips:
        ips.append('127.0.0.1')

    # IP 分类排序
    # 优先级：192.168.x.x > 10.x.x.x > 其他 > 虚拟网卡
    priority_192 = []  # 192.168.x.x (家庭/办公网络)
    priority_10 = []   # 10.x.x.x (企业网络)
    other_ips = []     # 其他真实 IP
    virtual_ips = []   # 虚拟网卡 IP

    for ip in ips:
        if ip.startswith('192.168.'):
            priority_192.append(ip)
        elif ip.startswith('10.'):
            priority_10.append(ip)
        elif ip.startswith('172.'):
            # 检查是否是虚拟网卡
            parts = ip.split('.')
            if len(parts) >= 2:
                second = int(parts[1])
                # Docker: 172.17.x.x, 172.18.x.x
                # Windows 虚拟网卡: 172.16.x.x
                # 私有网络范围: 172.16-31.x.x
                if 16 <= second <= 31:
                    virtual_ips.append(ip)
                else:
                    other_ips.append(ip)
        elif ip.startswith('198.18.'):
            # Clash 等代理工具虚拟网卡
            virtual_ips.append(ip)
        else:
            other_ips.append(ip)

    # 重新组合：优先级从高到低
    ips = priority_192 + priority_10 + other_ips + virtual_ips

    # 将主要 IP 移到对应分类的第一位（保持分类顺序）
    main_ip = get_host_ip()
    if main_ip in ips:
        ips.remove(main_ip)
        # 根据主要 IP 的类型，插入到对应分类的开头
        if main_ip.startswith('192.168.'):
            insert_pos = 0
        elif main_ip.startswith('10.'):
            insert_pos = len(priority_192)
        else:
            insert_pos = len(priority_192) + len(priority_10)
        ips.insert(insert_pos, main_ip)

    # 在最前面添加 0.0.0.0（监听所有网卡）
    ips.insert(0, '0.0.0.0 (所有网卡)')

    return ips
