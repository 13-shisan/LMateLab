# backend/services/papers/config.py
import os


APP_DIR = os.getenv("APP_DIR", "/app/var")
PROJECT_PAPERS_DIR = os.path.join(APP_DIR, "papers")


def _default_papers_root_dir() -> str:
    env_value = (os.getenv("PAPERS_ROOT_DIR") or "").strip()
    if env_value:
        return env_value

    candidates = [
        "/storage/software/LMateLab/var/papers",  # 宿主机
        "/app/var/papers",                        # 容器
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path

    return "/app/var/papers"

def _default_knowledge_root_dir() -> str:
    env_value = (os.getenv("KNOWLEDGE_ROOT_DIR") or "").strip()
    if env_value:
        return env_value

    candidates = [
        "/storage/software/LMateLab/var/knowledge",  # 宿主机
        "/app/var/knowledge",                        # 容器
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path

    return "/app/var/knowledge"

# 兼容旧索引中写死的宿主机路径
HOST_PAPERS_ROOT_DIR = os.getenv(
    "HOST_PAPERS_ROOT_DIR",
    "/storage/software/LMateLab/var/papers",
)

HOST_KNOWLEDGE_ROOT_DIR = os.getenv(
    "HOST_KNOWLEDGE_ROOT_DIR",
    "/storage/software/LMateLab/var/knowledge",
)

ENDNOTE_JOURNAL_TXT = os.getenv(
    "ENDNOTE_JOURNAL_TXT",
    os.path.join(PROJECT_PAPERS_DIR, "journal.txt")
)

PAPERS_ROOT_DIR = _default_papers_root_dir()
KNOWLEDGE_ROOT_DIR = _default_knowledge_root_dir()


PAPERS_RAW_DIR = os.getenv(
    "PAPERS_RAW_DIR",
    os.path.join(PAPERS_ROOT_DIR, "raw")
)

PAPERS_LIBRARY_DIR = os.getenv(
    "PAPERS_LIBRARY_DIR",
    os.path.join(PAPERS_ROOT_DIR, "library")
)

PAPERS_INDEX_DIR = os.getenv(
    "PAPERS_INDEX_DIR",
    os.path.join(PAPERS_ROOT_DIR, "index")
)

PAPERS_METADATA_DIR = os.getenv(
    "PAPERS_METADATA_DIR",
    PAPERS_INDEX_DIR,
)

PAPERS_PROCESSED_DIR = os.getenv(
    "PAPERS_PROCESSED_DIR",
    os.path.join(PAPERS_ROOT_DIR, "processed")
)

KNOWLEDGE_RAW_PAPERS_DIR = os.getenv(
    "KNOWLEDGE_RAW_PAPERS_DIR",
    os.path.join(KNOWLEDGE_ROOT_DIR, "raw", "papers")
)

MANIFEST_PATH = os.getenv(
    "PAPERS_MANIFEST_PATH",
    os.path.join(PAPERS_INDEX_DIR, "ingest_manifest.json")
)

INDEX_PATH = os.getenv(
    "PAPERS_INDEX_PATH",
    os.path.join(PAPERS_INDEX_DIR, "papers_index.json")
)

PAPERS_LIBRARY_INDEX_PATH = INDEX_PATH

LEGACY_PAPERS_INDEX_PATH = os.getenv(
    "LEGACY_PAPERS_INDEX_PATH",
    os.path.join(APP_DIR, "papers", "metadata", "papers_index.json")
)

LEGACY_PAPERS_LIBRARY_DIR = os.getenv(
    "LEGACY_PAPERS_LIBRARY_DIR",
    os.path.join(APP_DIR, "papers", "library")
)

PAPERS_INDEX_TEMPLATE_DIR = os.getenv(
    "PAPERS_INDEX_TEMPLATE_DIR",
    os.path.join(PROJECT_PAPERS_DIR, "index")
)

PAPERS_TAXONOMY_TEMPLATE_PATH = os.getenv(
    "PAPERS_TAXONOMY_TEMPLATE_PATH",
    os.path.join(PAPERS_INDEX_TEMPLATE_DIR, "taxonomy.json")
)

PAPERS_JOURNAL_FEATURES_TEMPLATE_PATH = os.getenv(
    "PAPERS_JOURNAL_FEATURES_TEMPLATE_PATH",
    os.path.join(PAPERS_INDEX_TEMPLATE_DIR, "journal_features.yaml")
)

PAPERS_TAXONOMY_PATH = os.getenv(
    "PAPERS_TAXONOMY_PATH",
    os.path.join(PAPERS_INDEX_DIR, "taxonomy.json")
)

PAPERS_JOURNAL_FEATURES_PATH = os.getenv(
    "PAPERS_JOURNAL_FEATURES_PATH",
    os.path.join(PAPERS_INDEX_DIR, "journal_features.yaml")
)

LABEL_TREE_PATH = os.getenv(
    "PAPERS_LABEL_TREE_PATH",
    os.path.join(PAPERS_INDEX_DIR, "label_tree.json")
)

MAX_FILENAME_LEN = int(os.getenv("PAPERS_MAX_FILENAME_LEN", "64"))

TOPIC_LABELS = {
    "electrocatalysis": "电催化",
    "photocatalysis": "光催化",
    "machine_learning": "机器学习",
    "magnetism": "磁性",
    "mobility": "迁移率",
}

# 期刊名（可能是全称/缩写/带点号） -> 文件名/索引用的稳定 slug
JOURNAL_SLUG_MAP = {
    # Nature / Science 系列
    "Nature": "Nature",
    "Nature Catalysis": "NatureCatalysis",
    "Nature Communications": "NatCommun",
    "Nature Materials": "NatMater",
    "Nature Physics": "NatPhys",
    "Nature Chemistry": "NatChem",
    "Nature Energy": "NatEnergy",
    "Nature Machine Intelligence": "NatMachIntell",
    "Nature Reviews Physics": "NatRevPhys",
    "Nat. Rev. Phys.": "NatRevPhys",
    "Nature Rev Phys": "NatRevPhys",
    "Nature Reviews Materials": "NatRevMater",
    "Nat. Rev. Mater.": "NatRevMater",
    "Nature Reviews Chemistry": "NatRevChem",
    "Nat. Rev. Chem.": "NatRevChem",

    "Science": "Science",
    "Science Advances": "SciAdv",

    "Proceedings of the National Academy of Sciences": "PNAS",
    "PNAS": "PNAS",

    # ACS / RSC / Wiley 常见
    "ACS Catalysis": "ACSCatalysis",
    "ACS Nano": "ACSNano",
    "Nano Letters": "NanoLett",
    "ACS Applied Materials & Interfaces": "ACSAMI",
    "ACS Appl. Mater. Interfaces": "ACSAMI",

    "JACS": "JACS",
    "Journal of the American Chemical Society": "JACS",
    "J. Am. Chem. Soc.": "JACS",
    "JACS Au": "JACSAu",

    "Chemical Science": "ChemSci",
    "Chem. Sci.": "ChemSci",

    "Angewandte Chemie International Edition": "AngewChemIntEd",
    "Angew. Chem. Int. Ed.": "AngewChemIntEd",

    "Chemistry of Materials": "ChemMater",
    "Journal of Materials Chemistry A": "JMaterChemA",
    "Journal of Materials Chemistry B": "JMaterChemB",
    "Journal of Materials Chemistry C": "JMaterChemC",

    # Advanced 系列
    "Advanced Materials": "AdvMater",
    "Advanced Functional Materials": "AdvFunctMater",
    "Advanced Science": "AdvSci",
    "Advanced Energy Materials": "AdvEnergyMater",
    "Small": "Small",

    # EES（两种写法）
    "Energy & Environmental Science": "EES",
    "Energy and Environmental Science": "EES",

    # APS / Physical Review 系列
    "Physical Review Letters": "PRL",
    "Phys. Rev. Lett.": "PRL",
    "PRL": "PRL",

    "Physical Review B": "PRB",
    "Phys. Rev. B": "PRB",
    "PRB": "PRB",

    "Physical Review Materials": "PRMaterials",
    "Phys. Rev. Materials": "PRMaterials",

    "Physical Review Research": "PRResearch",
    "Phys. Rev. Research": "PRResearch",

    "Reviews of Modern Physics": "RMP",
    "Rev. Mod. Phys.": "RMP",

    # AIP / 常见应用物理
    "Applied Physics Letters": "APL",
    "Appl. Phys. Lett.": "APL",

    "Journal of Applied Physics": "JAP",
    "J. Appl. Phys.": "JAP",

    # 已有：npj
    "npj Computational Materials": "npjComputMater",
    
    "J. Am. Chem. Soc": "JACS",
    "J Am Chem Soc": "JACS",
    "Nat Rev Phys": "NatRevPhys",
    "Nat. Rev. Phys": "NatRevPhys",
    "Adv. Funct. Mater.": "AdvFunctMater",
    "Adv. Funct. Mater": "AdvFunctMater",
    "Nano Lett.": "NanoLett",
    "Nano Lett": "NanoLett",
    "PHYSICAL REVIEW B": "PRB",
    "PHYSICAL REVIEW LETTERS": "PRL",
    "Physical Review Materials": "PRMaterials",
    "PHYSICAL REVIEW MATERIALS": "PRMaterials",
    "Phys. Rev. Materials": "PRMaterials",

    "Physical Review Applied": "PRApplied",
    "PHYSICAL REVIEW APPLIED": "PRApplied",
    "Phys. Rev. Applied": "PRApplied",

}
