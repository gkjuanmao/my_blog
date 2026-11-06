// Jenkins CI/CD —— 门禁 → 构建镜像 → 部署到本机 podman
//
// 流水线本身跑在 Jenkins 容器里（192.168.31.61:8080），构建工具链在
// /var/jenkins_home/tools/{uv,node}；镜像构建与部署在宿主执行，由
// ~/.local/bin/jenkins-deploy.sh 通过受限 SSH 完成（失败自动回滚）。
//
// 触发：Gitea push webhook → POST /job/my_blog/build
// 兜底：pollSCM 每 2 分钟比对一次远端 HEAD

pipeline {
  agent any

  options {
    timestamps()
    buildDiscarder(logRotator(numToKeepStr: '20'))
    timeout(time: 60, unit: 'MINUTES')
  }

  environment {
    PATH                 = "/var/jenkins_home/tools/bin:${env.PATH}"
    UV_PYTHON_PREFERENCE = 'only-managed'
    NPM_CONFIG_REGISTRY  = 'https://registry.npmmirror.com'
    DEPLOY_KEY           = '/var/jenkins_home/.ssh/jenkins_deploy'
    DEPLOY_HOST          = 'host.containers.internal'
  }

  triggers {
    // webhook 失效时的兜底，代价只是一次 git ls-remote
    pollSCM('H/2 * * * *')
  }

  stages {
    stage('Toolchain') {
      steps {
        sh '''
          set -e
          uv --version && node -v && npm -v
          # CPython 由 uv 托管；缺失时才走宿主代理下载（装过一次就命中缓存）
          if ! uv python find 3.12 >/dev/null 2>&1; then
            HTTPS_PROXY=http://host.containers.internal:12450 uv python install 3.12
          fi
        '''
      }
    }

    stage('Checkout') {
      steps {
        checkout scm
        script {
          env.GIT_SHA = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
          echo "commit: ${env.GIT_SHA}"
        }
      }
    }

    stage('Backend 门禁') {
      steps {
        sh '''
          set -e
          uv sync --frozen
          uv run ruff check .
          uv run mypy config articles common users
          uv run python manage.py makemigrations --check --dry-run
          mkdir -p reports
          uv run pytest -q --junitxml=reports/junit.xml
        '''
      }
    }

    stage('Frontend 门禁') {
      steps {
        dir('front') {
          sh '''
            set -e
            npm ci --no-audit --no-fund
            npm run lint
            npx vue-tsc --noEmit
            npm test
          '''
        }
      }
    }

    stage('Deploy') {
      steps {
        sh '''
          set -e
          ssh -i "$DEPLOY_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 \
              "yquian@$DEPLOY_HOST" "deploy $GIT_SHA"
        '''
      }
    }
  }

  post {
    always {
      junit allowEmptyResults: true, testResults: 'reports/junit.xml'
      archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
    }
    failure {
      echo '流水线失败：deploy.sh 会自行回滚镜像；请查看 Deploy 阶段输出。'
    }
  }
}
