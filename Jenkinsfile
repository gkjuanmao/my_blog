// Jenkins CI/CD —— 门禁 → 构建镜像 → 部署到本机 podman
//
// 流水线本身跑在 Jenkins 容器里（192.168.31.61:8080），构建工具链在
// /var/jenkins_home/tools/{uv,node}；镜像构建与部署在宿主执行，由
// ~/.local/bin/jenkins-deploy.sh 通过受限 SSH 完成（失败自动回滚）。
//
// 触发：Gitea push webhook → POST /job/my_blog/build
// 兜底：pollSCM 每 2 分钟比对一次远端 HEAD
//
// 邮件：post 阶段调用 scripts/ci_mail_report.py，生成 HTML 正文与
// PNG 趋势图（内嵌 cid:trend.png），门禁/用例/构建情况一屏展示。

// 运行一个门禁命令，记录 PASS/FAIL 与耗时。
// 不抛异常，由 stage 汇总后统一决定是否失败。
def runGate(String key, String cmd, String workDir = '.') {
  def start = System.currentTimeMillis()
  def rc = 0
  dir(workDir) {
    rc = sh(returnStatus: true, script: cmd)
  }
  def ms = System.currentTimeMillis() - start
  writeFile file: "reports/gates/${key}.txt", text: "${rc == 0 ? 'PASS' : 'FAIL'}\t${ms}\n"
  echo "gate ${key}: ${rc == 0 ? 'PASS' : 'FAIL'} (${ms} ms)"
  return rc
}

pipeline {
  agent any

  options {
    timestamps()
    // 串行执行：部署脚本与趋势历史文件都不适合并发写
    disableConcurrentBuilds()
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
          # 清掉上一次构建的门禁/测试/部署产物，避免本次跳过时误报
          rm -rf reports/gates
          rm -f reports/pytest.xml reports/vitest.xml reports/deploy.log \
                reports/email.html reports/trend.png reports/email-subject.txt
          mkdir -p reports/gates

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
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          script {
            def failed = false
            if (runGate('backend.setup', 'uv sync --frozen') != 0) {
              failed = true
            } else {
              if (runGate('backend.ruff', 'uv run ruff check .') != 0) { failed = true }
              if (runGate('backend.mypy', 'uv run mypy config articles common users') != 0) { failed = true }
              if (runGate('backend.migrations', 'uv run python manage.py makemigrations --check --dry-run') != 0) { failed = true }
              if (runGate('backend.pytest', 'uv run pytest -q --junitxml=reports/pytest.xml') != 0) { failed = true }
            }
            if (failed) {
              error('后端门禁未通过')
            }
          }
        }
      }
    }

    stage('Frontend 门禁') {
      steps {
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          script {
            def failed = false
            if (runGate('frontend.setup', 'npm ci --no-audit --no-fund', 'front') != 0) {
              failed = true
            } else {
              if (runGate('frontend.eslint', 'npm run lint', 'front') != 0) { failed = true }
              if (runGate('frontend.vuetsc', 'npx vue-tsc --noEmit', 'front') != 0) { failed = true }
              // junit reporter 产出 XML，交给 junit 插件与后端结果合并展示
              if (runGate('frontend.vitest', 'npm test -- --reporter=default --reporter=junit --outputFile=../reports/vitest.xml', 'front') != 0) { failed = true }
            }
            if (failed) {
              error('前端门禁未通过')
            }
          }
        }
      }
    }

    stage('Deploy') {
      // 任何门禁失败都不部署；catchError 已把构建标记为 FAILURE
      when {
        expression { currentBuild.currentResult == 'SUCCESS' }
      }
      steps {
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          script {
            def start = System.currentTimeMillis()
            // 用 bash 保证 pipefail：ssh 失败时 tee 不会把退出码吞成 0
            def rc = sh(returnStatus: true, script: '''
              mkdir -p reports
              bash -o pipefail -c 'ssh -i "$DEPLOY_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "yquian@$DEPLOY_HOST" "deploy $GIT_SHA" 2>&1 | tee reports/deploy.log'
            ''')
            def ms = System.currentTimeMillis() - start
            writeFile file: 'reports/gates/deploy.txt', text: "${rc == 0 ? 'PASS' : 'FAIL'}\t${ms}\n"
            if (rc != 0) {
              error('部署失败')
            }
          }
        }
      }
    }
  }

  post {
    always {
      // 后端 pytest 与前端 vitest 的结果合并进同一份测试报告 / 趋势图
      junit allowEmptyResults: true, testResults: 'reports/pytest.xml'
      junit allowEmptyResults: true, testResults: 'reports/vitest.xml'

      script {
        env.REPORT_RESULT = currentBuild.currentResult
        env.REPORT_DURATION_MS = String.valueOf(System.currentTimeMillis() - currentBuild.startTimeInMillis)
        try {
          sh '''
            uv run --no-project python scripts/ci_mail_report.py \
              --workspace . \
              --history-dir "$WORKSPACE/../ci-trend" \
              --job "$JOB_NAME" \
              --build "$BUILD_NUMBER" \
              --sha "${GIT_SHA:-unknown}" \
              --result "$REPORT_RESULT" \
              --duration-ms "$REPORT_DURATION_MS" \
              --url "$BUILD_URL" \
              --deploy-log reports/deploy.log
          '''
        } catch (e) {
          echo "报告生成失败: ${e}"
          writeFile file: 'reports/email.html', text: "<html><body style=\"font-family:Arial,sans-serif\"><p>报告生成失败，请查看构建：<a href=\"${env.BUILD_URL}\">${env.BUILD_URL}</a></p></body></html>"
          writeFile file: 'reports/email-subject.txt', text: "[Jenkins] ${env.JOB_NAME} #${env.BUILD_NUMBER} · ${env.REPORT_RESULT}"
        }
      }

      archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true

      script {
        def subject = "[Jenkins] ${env.JOB_NAME} #${env.BUILD_NUMBER} · ${env.REPORT_RESULT}"
        try {
          subject = readFile('reports/email-subject.txt').trim()
        } catch (e) { }

        def body = "<html><body><p>报告文件缺失，请查看 ${env.BUILD_URL}</p></body></html>"
        try {
          body = readFile('reports/email.html')
        } catch (e) { }

        def chart = fileExists('reports/trend.png') ? 'reports/trend.png' : null
        emailext(
          to: '765674897@qq.com',
          subject: subject,
          body: body,
          mimeType: 'text/html',
          attachLog: (env.REPORT_RESULT != 'SUCCESS'),
          inlineAttachmentsPattern: chart
        )
      }
    }
  }
}
