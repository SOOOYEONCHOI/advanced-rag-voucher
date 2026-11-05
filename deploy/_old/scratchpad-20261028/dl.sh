set -e
sed -i -e 's|^mirrorlist=|#mirrorlist=|' \
       -e 's|^#\?baseurl=http://dl.rockylinux.org/\$contentdir/\$releasever|baseurl=https://dl.rockylinux.org/vault/rocky/9.6|' \
       /etc/yum.repos.d/rocky*.repo
dnf clean all -q
dnf repolist -v 2>/dev/null | grep -i "repo-baseurl" | head
dnf -y -q install dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
dnf list docker-ce --showduplicates 2>/dev/null | sort -r | head -3
dnf -y install --downloadonly --downloaddir=/out --setopt=install_weak_deps=False \
    docker-ce-29.9.2 docker-ce-cli-29.9.2 containerd.io docker-compose-plugin 2>&1 | tail -5
ls /out | sort
du -sh /out
