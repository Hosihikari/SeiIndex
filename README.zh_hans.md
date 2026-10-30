# SeiIndex

[English](README.md) | [简体中文](README.zh_hans.md)

Seiko 的官方静态索引。Seiko 把它当作普通源使用：

```hocon
sources = [
  { id = "official", index = "https://raw.githubusercontent.com/Hosihikari/SeiIndex/main/index.json" }
]
```

`sk init` 默认写入这个源。这个 URL 只是默认值：任何同布局的静态 HTTPS 索引或本地目录都可以使用，私有索引使用同一格式。

## 布局

```
index.json          schemaVersion、generatedBy，以及 `sk search` 使用的 sei 名称列表
sei/<name>.json     一个 sei 的全部版本与构件
```

任何项目都可以通过提交 issue 表单提交自己的 `sei/<name>.json`；索引机器人会把它转成 pull request。没有 `sk publish`；构件托管由发布者自己负责，本仓库只记录稳定的 URL 与校验和。

## 提交 sei

1. 构建一个根目录含 `sei.json` 与载荷的 zip。允许嵌套目录；载荷路径相对安装根部署。
2. 将 zip 托管在稳定、公开的 URL。最简单的是钉在标签上的 GitHub Release 资产；对象存储与静态站点也可以。
3. 打开 **Submit a sei version** issue：https://github.com/Hosihikari/SeiIndex/issues/new?template=sei-submission.yml，填写 sei 名称与完整的版本条目 JSON（构件、可选的依赖与选择器）。
4. 对本仓库有写权限的账号会自动处理；其他作者需要维护者添加 `index-submission` 标签。
5. 索引机器人把条目追加到 `sei/<name>.json`、把名称加入 `index.json`、打开 pull request、批准 GitHub 为该 PR 暂扣的 **Validate index** 运行，并启用自动合并。校验通过后 PR 自动合并，合并时关闭 issue。

pull request 不是提交渠道。组织外作者提交的、只改动索引数据的 PR 会被关闭并指向 issue 表单；维护者仍可以用 PR 做其他改动。索引机器人的 PR 只改数据，且不会由外部贡献者创建。

提交 issue 在 PR 校验期间带 `validation-pending` 标签；校验不通过改为 `validation-failed`，通过则改为 `validation-passed`。PR 正文包含 `Closes #<issue>`，合并时关闭 issue。30 天内未通过校验的提交 issue 会以 not planned 关闭。

## 合并

有写权限的账号与机器人提交的纯数据 PR 会自动启用 GitHub 自动合并；**Validate index** 的 `validate` 检查通过后，直接 squash 合并，不再另行审查。

改动其他文件（包括 `.github/` 与本 README）的 PR 不会自动合并，由维护者审查后合并。这样 CI 改动就不会进入自动合并——否则一个能改工作流的 PR 就能自己满足检查。

sei 名称必须可安全用作路径：不能含 `/`、`\`、`:`、`*`、`?`、`"`、`<`、`>`、`|`，不能含控制字符，不能以空格或点开头或结尾。文件名、`name` 字段与 `index.json` 中的条目必须一致。

## 规则

- **版本不可变。** 只能追加新版本；不得修改已有版本条目或删除版本。
- **已有版本只能改 `yanked` 与 `deprecated`。** `yanked: true` 会让新解析忽略该版本，但锁回放仍可使用；`deprecated` 是给人看的迁移提示。
- **不得删除 sei 或版本。** 退役方式是 yank 或 deprecate。
- **`index.json` 的 `sei` 列表只能增长。** 删除名称会破坏搜索，会被拒绝。
- **构件必须是 zip 归档**，根目录恰好一份 `sei.json`（当前存储只解 zip）。
- **索引条目必须与内嵌 `sei.json` 一致**：`schemaVersion`、`name`、`version`、`dependencies`、`selectors` 与 `layout`。
- **校验和必须精确。** `sha256` 是 64 位小写十六进制，`size` 是归档字节数；CI 会下载每个构件并核对两者。

## Schema

`index.json`：

```json
{
  "schemaVersion": 1,
  "generatedBy": "SeiIndex maintainers",
  "sei": ["hello-csharp"]
}
```

`sei/hello-csharp.json`：

```json
{
  "schemaVersion": 1,
  "name": "hello-csharp",
  "versions": [
    {
      "version": "1.0.0",
      "dependencies": [
        { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
      ],
      "artifacts": [
        {
          "selectors": { "rid": "win-x64" },
          "layout": "root",
          "source": {
            "url": "https://github.com/example/hello-csharp/releases/download/v1.0.0/hello-csharp-win-x64.zip",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "size": 12345
          }
        }
      ],
      "yanked": false,
      "deprecated": null
    }
  ]
}
```

该构件的 zip 根级 `sei.json`：

```json
{
  "schemaVersion": 1,
  "name": "hello-csharp",
  "version": "1.0.0",
  "dependencies": [
    { "name": "hosihikari", "version": "[1.1.0,1.2.0)" }
  ],
  "selectors": { "rid": "win-x64" },
  "layout": "root",
  "modes": { "hello-csharp": "0755" }
}
```

字段：

- `version` 使用 NuGet SemVer。默认排除预发布版，除非声明中要求。
- `dependencies[].version` 是 NuGet 版本范围；`null`、省略或 `"*"` 表示任意版本。
- `selectors.rid` 匹配目标平台，例如 `win-x64` 或 `linux-arm64`。其他选择器键的值是必须出现在依赖图中的 sei 名（`carrier` 约定）。平台无关的构件省略 `selectors`。
- `layout` 为 `root`（或省略）。其他形状暂不支持。
- `modes` 只属于 `sei.json`；它设置 Unix 可执行位，例如 `{ "sk": "0755" }`。Windows 忽略。

每个版本至少需要一个构件；同一版本中的两个构件不能有完全相同的选择器。

## 本地校验

```bash
sk index verify . --check-artifacts --strict
```

命令会打印发现的问题，出错时以非零退出（`--strict` 时警告也算失败）。`--json` 输出 Seiko 常用的信封。CI 使用固定版本的 `sk` 运行同一命令，并用 `git diff` 检查追加规则。
