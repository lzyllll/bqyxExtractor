"""SWF 资源下载与更新管理器。

负责从 4399 下载主 SWF、检测游戏版本更新、解包主程序二进制、
反编译基础 AS3 常量与 XML 数据包，并根据加载器配置下载补齐全部依赖 SWF。
"""
from __future__ import annotations

import logging
from pathlib import Path

from bqyx_parser.downloader import SWFDownloader
from bqyx_parser.extractor import (
    BqAS3Parser,
    FFDecExporter,
    extract_swf_urls,
    save_define_modules_json,
)
from bqyx_parser.tools import FileProcessor, load_last_main_swf, load_last_version, save_main_swf_info

logger = logging.getLogger(__name__)


class SWFUpdater:
    """SWF 资源下载与版本更新管理器，仅负责 SWF 的下载、版本检测、反编译主包以及依赖更新。"""

    def __init__(
        self,
        ffdec_path: str,
        download_url: str = "https://sbai.4399.com/4399swf/upload_swf/ftp15/linxy/20150324/gun/",
        swf_dir: str = "swf_assets",
    ):
        self.ffdec_path = ffdec_path
        self.base_url = download_url
        self.root_dir = Path(swf_dir)
        self.force_update = False
        self.version = load_last_version()

        FFDecExporter.set_ffdec_path(ffdec_path)
        self.downloader = SWFDownloader(swf_dir, download_url)
        self.file_processor = FileProcessor()
        self.as3_extractor = BqAS3Parser()

    def set_force_update(self, force: bool) -> None:
        """是否忽略本地版本记录，强制重新下载。"""
        self.force_update = force

    async def update_all_swf(self) -> None:
        """下载主 SWF，反编译 XML/AS3，再补齐依赖的资源 SWF。"""
        logger.info("开始运行BQYX所有swf资源及xml...")
        main_swf = await self.downloader.get_main_swf()
        logger.info("获取到主SWF文件: %s", main_swf)

        version_stem = Path(main_swf).stem
        self.downloader.update_root_dir(self.root_dir / version_stem)

        last_main_swf = load_last_main_swf()
        if last_main_swf == main_swf and not self.force_update:
            logger.info("当前版本没有更新，如需强制更新请设置force_update=True")
            return

        save_main_swf_info(main_swf)
        self.version = version_stem
        logger.info("已保存当前版本信息")

        local_main_swf = await self.downloader.download(main_swf)
        main_game_compiled = Path("compiled") / self.version
        logger.info("导出主游戏的二进制数据(swf文件)到: %s", main_game_compiled)

        FFDecExporter(input_swf=local_main_swf, output_dir=main_game_compiled).export_binary_data()
        self.file_processor.rename_bin_to_swf(main_game_compiled)

        game_swf_path = main_game_compiled / "L4399Main_gamefile.swf"
        if not game_swf_path.exists():
            logger.info("所有操作完成！")
            return

        exporter = FFDecExporter(input_swf=game_swf_path, output_dir=main_game_compiled)
        # 只导出需要的 AS3，避免整包脚本全导出
        exporter.export_scripts()

        main_game_project = main_game_compiled / "scripts"
        version_dic = self.as3_extractor.extract_specific_constants(main_game_project)
        self.extract_define_module_map(main_game_project)

        if "xmlSwfUrl" in version_dic:
            await self.downloader.download(version_dic["xmlSwfUrl"])
            xml_swf = self.downloader.root_dir / version_dic["xmlSwfUrl"]
            xml_compiled = main_game_compiled / "xml"
            FFDecExporter(input_swf=xml_swf, output_dir=xml_compiled).export_binary_data()
            self.file_processor.rename_xml_bin(xml_compiled)
            self.file_processor.clean_xml_files(xml_compiled)
            logger.info("XML文件已解析并清理到: %s", xml_compiled)
            await self._download_all_swf_files(main_game_project, xml_compiled)

        logger.info("所有操作完成！")

    def extract_define_module_map(self, project_path: Path) -> dict[str, list[str]]:
        """从 DefineGroup.as 提取模块 XML 映射，保存到 output/<version>/define_modules.json。"""
        modules = self.as3_extractor.extract_define_modules(project_path)
        if not modules:
            logger.warning("未提取到 DefineGroup 模块映射")
            return {}

        output_path = Path("output") / self.version / "define_modules.json"
        save_define_modules_json(modules, output_path)
        logger.info(
            "DefineGroup 模块映射已保存: %s (%d modules)",
            output_path,
            len(modules),
        )
        return modules

    async def _download_all_swf_files(self, project_path: Path, xml_dir: Path) -> None:
        """合并 XML 与 AS3 中的 SWF 路径后批量下载。"""
        swf_urls_from_xml = extract_swf_urls(xml_dir)
        swf_loaders = self.as3_extractor.extract_swf_loaders(project_path)
        swf_urls_from_loaders = [rel_path for rel_path, _, _ in swf_loaders]
        all_swf_urls = list(set(swf_urls_from_xml + swf_urls_from_loaders))
        logger.info("开始下载 %s 个SWF文件...", len(all_swf_urls))
        await self.downloader.download_multiple(all_swf_urls)
        logger.info("所有SWF文件下载完毕")


# 兼容旧名称
BQYXParserApp = SWFUpdater
