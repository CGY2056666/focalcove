from __future__ import annotations

import re

from .models import GoalProfile
from .utils import dedupe_terms, extract_meaningful_tokens, normalize_spaces, normalize_text


DEFAULT_GOAL_TEXT = "围绕当前任务持续处理目标内容，减少与目标无关的页面切换"
GOAL_PLACEHOLDER = "例如：完成数学作业，避免切去聊天和短视频"
GOAL_EXAMPLES = [
    "学习复习：阅读课程资料并整理本章重点，不分心去看娱乐内容",
    "娱乐放松：观看喜欢的视频或音乐，放松心情不被其他信息打扰",
    "日常办公：整理电子邮件、文档和日终报告，集中精力完成办公任务",
    "运动规划：制定健身计划、记录训练数据，保持运动专注力",
]

_GENERIC_SUPPORT_KEYWORDS = [
    "任务",
    "目标",
    "步骤",
    "资料",
    "正文",
    "内容",
    "结果",
    "页面",
    "记录",
    "整理",
    "study",
    "task",
    "goal",
    "document",
    "page",
    "result",
    "note",
]
_GENERIC_STRUCTURE_HINTS = [
    "标题-正文结构",
    "列表-详情结构",
    "步骤-结果结构",
    "对比-结论结构",
    "搜索-结果结构",
    "清单-记录结构",
]
_NEGATIVE_KEYWORDS = {
    "strong": ["短视频", "直播", "游戏", "douyin", "xhs", "reels"],
    "medium": ["聊天", "消息", "朋友圈", "微信", "qq", "微博", "私信"],
    "weak": ["评论", "推荐", "热榜", "娱乐", "刷屏"],
}
_DYNAMIC_HINT_RULES = [
    # ===== 数学类（4条） =====
    {
        "patterns": ["calculus", "mathematical analysis", "高等数学", "高数", "数学分析", "微积分", "极限", "导数", "积分", "微分", "级数", "泰勒展开", "傅里叶"],
        "support": ["函数", "极限", "导数", "积分", "微分方程", "级数", "收敛", "发散", "连续", "可微", "偏导", "重积分", "曲线积分", "曲面积分", "格林公式", "斯托克斯", "高斯公式"],
        "semantic": ["function", "limit", "derivative", "integral", "differential", "series", "convergence", "continuity", "differentiability", "partial derivative", "multiple integral", "vector calculus", "Green", "Stokes", "Gauss"],
        "structure": ["定义-定理-证明结构", "例题-解答结构", "公式推导结构", "图像-性质结构"],
    },
    {
        "patterns": ["linear algebra", "matrix", "向量", "矩阵", "线性代数", "特征值", "特征向量", "行列式", "秩", "线性空间", "线性变换", "正交", "相似", "合同"],
        "support": ["矩阵", "向量", "行列式", "秩", "特征值", "特征向量", "线性变换", "基", "维数", "子空间", "正交矩阵", "对称矩阵", "二次型", "Jordan标准型", "SVD"],
        "semantic": ["matrix", "vector", "determinant", "rank", "eigenvalue", "eigenvector", "linear transformation", "basis", "dimension", "subspace", "orthogonal", "symmetric", "quadratic form", "Jordan", "singular value decomposition"],
        "structure": ["定义-性质-例题结构", "矩阵运算-验证结构", "证明-推导结构"],
    },
    {
        "patterns": ["probability", "statistics", "概率论", "数理统计", "随机变量", "分布", "期望", "方差", "假设检验", "置信区间", "回归分析", "贝叶斯", "大数定律", "中心极限定理"],
        "support": ["概率", "随机变量", "分布函数", "密度函数", "期望", "方差", "协方差", "相关系数", "样本", "总体", "估计", "假设检验", "置信区间", "回归", "方差分析", "贝叶斯公式"],
        "semantic": ["probability", "random variable", "distribution", "PDF", "CDF", "expectation", "variance", "covariance", "correlation", "sample", "population", "estimation", "hypothesis testing", "confidence interval", "regression", "ANOVA", "Bayesian", "LLN", "CLT"],
        "structure": ["概念-公式-例题结构", "数据-统计量-推断结构", "模型-参数-检验结构"],
    },
    {
        "patterns": ["discrete mathematics", "离散数学", "图论", "集合论", "数理逻辑", "组合数学", "排列组合", "布尔代数", "关系", "群论", "环论", "域论"],
        "support": ["集合", "关系", "函数", "图", "树", "路径", "连通", "欧拉", "哈密顿", "命题逻辑", "谓词逻辑", "布尔代数", "群", "环", "域", "同态", "同构"],
        "semantic": ["set", "relation", "function", "graph", "tree", "path", "connectivity", "Euler", "Hamilton", "propositional logic", "predicate logic", "Boolean algebra", "group", "ring", "field", "homomorphism", "isomorphism"],
        "structure": ["定义-定理-证明结构", "图-性质-算法结构", "逻辑公式-推演结构"],
    },

    # ===== 物理类（4条） =====
    {
        "patterns": ["general physics", "大学物理", "普通物理", "力学", "运动学", "动力学", "牛顿定律", "能量守恒", "动量守恒", "刚体", "振动", "波动"],
        "support": ["位移", "速度", "加速度", "力", "质量", "牛顿定律", "功", "能", "动量", "角动量", "转动惯量", "简谐振动", "阻尼振动", "机械波", "多普勒效应"],
        "semantic": ["displacement", "velocity", "acceleration", "force", "mass", "Newton's laws", "work", "energy", "momentum", "angular momentum", "moment of inertia", "simple harmonic motion", "damped oscillation", "mechanical wave", "Doppler effect"],
        "structure": ["概念-定律-例题结构", "物理模型-公式推导-计算结构", "实验-数据-结论结构"],
    },
    {
        "patterns": ["electromagnetism", "电动力学", "电磁学", "静电场", "静磁场", "Maxwell方程", "高斯定理", "安培环路", "法拉第电磁感应", "电磁波", "电势", "磁势"],
        "support": ["电场", "磁场", "电势", "磁势", "电荷", "电流", "电容", "电感", "电阻", "高斯定理", "安培环路定理", "法拉第定律", "麦克斯韦方程组", "电磁波", "Poynting矢量", "Lorentz力"],
        "semantic": ["electric field", "magnetic field", "potential", "charge", "current", "capacitance", "inductance", "resistance", "Gauss's law", "Ampere's law", "Faraday's law", "Maxwell's equations", "electromagnetic wave", "Poynting vector", "Lorentz force"],
        "structure": ["定律-公式推导-应用结构", "场-势-能量结构", "边界条件-求解结构"],
    },
    {
        "patterns": ["optics", "光学", "几何光学", "物理光学", "波动光学", "干涉", "衍射", "偏振", "透镜", "成像", "Fourier光学", "全息"],
        "support": ["折射", "反射", "透镜", "成像", "放大率", "干涉", "衍射", "光栅", "偏振", "双折射", "Fourier光学", "全息", "激光", "光纤", "光谱"],
        "semantic": ["refraction", "reflection", "lens", "imaging", "magnification", "interference", "diffraction", "grating", "polarization", "birefringence", "Fourier optics", "holography", "laser", "optical fiber", "spectrum"],
        "structure": ["光路-成像-计算结构", "波前-干涉-条纹结构", "实验-测量-分析结构"],
    },
    {
        "patterns": ["quantum mechanics", "量子力学", "量子物理", "薛定谔方程", "波函数", "算符", "本征值", "不确定性原理", "角动量", "自旋", "氢原子", "微扰论"],
        "support": ["波函数", "薛定谔方程", "Hamiltonian", "算符", "本征值", "本征函数", "不确定性原理", "对易关系", "角动量", "自旋", "Pauli矩阵", "氢原子", "微扰论", "变分法", "散射"],
        "semantic": ["wave function", "Schrodinger equation", "Hamiltonian", "operator", "eigenvalue", "eigenfunction", "uncertainty principle", "commutator", "angular momentum", "spin", "Pauli matrices", "hydrogen atom", "perturbation theory", "variational method", "scattering"],
        "structure": ["公设-算符-方程结构", "模型-求解-物理解释结构", "近似方法-修正-验证结构"],
    },

    # ===== 化学类（4条） =====
    {
        "patterns": ["inorganic chemistry", "无机化学", "元素化学", "配位化学", "氧化还原", "酸碱化学"],
        "support": ["元素", "化合物", "化学键", "分子轨道", "价键理论", "杂化轨道", "VSEPR", "配位化合物", "氧化还原", "酸碱", "电化学", "化学平衡", "热化学", "光谱"],
        "semantic": ["element", "compound", "chemical bond", "molecular orbital", "valence bond", "hybridization", "VSEPR", "coordination compound", "redox", "acid-base", "electrochemistry", "equilibrium", "thermochemistry", "spectroscopy"],
        "structure": ["反应-机理-产物结构", "结构-性质-应用结构", "实验-数据-分析结构"],
    },
    {
        "patterns": ["organic chemistry", "有机化学", "有机合成", "反应机理", "官能团", "立体化学"],
        "support": ["烷烃", "烯烃", "炔烃", "芳香烃", "卤代烃", "醇", "酚", "醚", "醛", "酮", "羧酸", "酯", "胺", "酰胺", "官能团", "反应机理", "亲核取代", "亲电加成", "消除反应", "重排", "保护基", "合成路线"],
        "semantic": ["alkane", "alkene", "alkyne", "aromatic", "halohydrocarbon", "alcohol", "phenol", "ether", "aldehyde", "ketone", "carboxylic acid", "ester", "amine", "amide", "functional group", "reaction mechanism", "nucleophilic substitution", "electrophilic addition", "elimination", "rearrangement", "protecting group", "synthetic route"],
        "structure": ["反应物-机理-产物结构", "合成路线-步骤-验证结构", "结构-光谱-鉴定结构"],
    },
    {
        "patterns": ["analytical chemistry", "分析化学", "仪器分析", "色谱", "光谱分析", "电分析", "滴定"],
        "support": ["滴定", "酸碱滴定", "氧化还原滴定", "配位滴定", "沉淀滴定", "重量分析", "吸光光度法", "原子吸收", "原子发射", "色谱", "气相色谱", "液相色谱", "质谱", "核磁共振", "红外光谱", "紫外可见", "电化学分析", "电位分析", "极谱"],
        "semantic": ["titration", "acid-base titration", "redox titration", "complexometric titration", "precipitation titration", "gravimetric analysis", "spectrophotometry", "atomic absorption", "atomic emission", "chromatography", "GC", "HPLC", "mass spectrometry", "NMR", "IR", "UV-Vis", "electrochemical analysis", "potentiometry", "polarography"],
        "structure": ["样品-前处理-测定结构", "标准曲线-定量-误差结构", "谱图-解析-鉴定结构"],
    },
    {
        "patterns": ["physical chemistry", "物理化学", "化学热力学", "化学动力学", "电化学", "表面化学", "胶体化学", "高分子化学"],
        "support": ["热力学第一定律", "热力学第二定律", "熵", "Gibbs自由能", "化学势", "相平衡", "相图", "化学平衡", "反应速率", "速率方程", "活化能", "催化", "电化学", "电极电势", "Nernst方程", "表面张力", "吸附", "胶体", "高分子", "聚合", "分子量"],
        "semantic": ["first law of thermodynamics", "second law", "entropy", "Gibbs free energy", "chemical potential", "phase equilibrium", "phase diagram", "chemical equilibrium", "reaction rate", "rate equation", "activation energy", "catalysis", "electrochemistry", "electrode potential", "Nernst equation", "surface tension", "adsorption", "colloid", "polymer", "polymerization", "molecular weight"],
        "structure": ["定律-公式-计算结构", "实验-数据处理-结论结构", "模型-参数-验证结构"],
    },

    # ===== 生物类（4条） =====
    {
        "patterns": ["cell biology", "细胞生物学", "细胞", "细胞器", "细胞膜", "细胞骨架", "细胞周期", "细胞信号"],
        "support": ["细胞", "细胞膜", "细胞核", "线粒体", "内质网", "高尔基体", "溶酶体", "过氧化物酶体", "细胞骨架", "微丝", "微管", "中间纤维", "细胞周期", "有丝分裂", "减数分裂", "细胞凋亡", "细胞信号转导", "受体", "第二信使", "细胞连接", "细胞外基质"],
        "semantic": ["cell", "cell membrane", "nucleus", "mitochondria", "ER", "Golgi", "lysosome", "peroxisome", "cytoskeleton", "microfilament", "microtubule", "intermediate filament", "cell cycle", "mitosis", "meiosis", "apoptosis", "signal transduction", "receptor", "second messenger", "cell junction", "extracellular matrix"],
        "structure": ["结构-功能-机制结构", "实验-观察-结论结构", "信号-转导-效应结构"],
    },
    {
        "patterns": ["genetics", "molecular biology", "遗传学", "分子生物学", "DNA", "RNA", "基因", "基因组", "基因工程", "PCR", "克隆"],
        "support": ["DNA", "RNA", "基因", "染色体", "等位基因", "显性", "隐性", "分离定律", "自由组合", "连锁互换", "突变", "重组", "转录", "翻译", "表达调控", "操纵子", "PCR", "电泳", "克隆", "载体", "限制性内切酶", "转基因"],
        "semantic": ["DNA", "RNA", "gene", "chromosome", "allele", "dominant", "recessive", "segregation", "independent assortment", "linkage", "mutation", "recombination", "transcription", "translation", "regulation", "operon", "PCR", "electrophoresis", "cloning", "vector", "restriction enzyme", "transgenic"],
        "structure": ["分子结构-功能-机制结构", "实验流程-结果-分析结构", "遗传-变异-进化结构"],
    },
    {
        "patterns": ["ecology", "evolution", "生态学", "进化论", "进化生物学", "物种", "种群", "群落", "生态系统"],
        "support": ["物种", "种群", "群落", "生态系统", "食物链", "食物网", "能量流动", "物质循环", "生产力", "分解者", "竞争", "捕食", "共生", "寄生", "自然选择", "适应", "遗传漂变", "基因流", "物种形成", "灭绝", "生物多样性"],
        "semantic": ["species", "population", "community", "ecosystem", "food chain", "food web", "energy flow", "nutrient cycle", "productivity", "decomposer", "competition", "predation", "symbiosis", "parasitism", "natural selection", "adaptation", "genetic drift", "gene flow", "speciation", "extinction", "biodiversity"],
        "structure": ["层次-结构-功能结构", "观察-描述-解释结构", "实验-假设-验证结构"],
    },
    {
        "patterns": ["physiology", "anatomy", "生理学", "解剖学", "人体解剖", "人体生理", "神经生理", "内分泌", "循环生理"],
        "support": ["细胞", "组织", "器官", "系统", "骨骼", "肌肉", "神经", "感觉", "运动", "内分泌", "激素", "循环", "心脏", "血管", "呼吸", "肺", "消化", "吸收", "排泄", "肾脏", "生殖", "免疫", "体温调节", "稳态"],
        "semantic": ["cell", "tissue", "organ", "system", "bone", "muscle", "nerve", "sensation", "movement", "endocrine", "hormone", "circulation", "heart", "blood vessel", "respiration", "lung", "digestion", "absorption", "excretion", "kidney", "reproduction", "immune", "thermoregulation", "homeostasis"],
        "structure": ["结构-功能-调节结构", "机制-通路-效应结构", "实验-测量-分析结构"],
    },

    # ===== 地学类（4条） =====
    {
        "patterns": ["geography", "自然地理", "人文地理", "地理学", "地貌", "水文", "土壤", "植被"],
        "support": ["地形", "地貌", "气候", "水文", "河流", "湖泊", "冰川", "地下水", "土壤", "植被", "生态系统", "人口", "城市", "农业", "工业", "交通", "区域", "GIS", "遥感", "地图", "坐标", "投影"],
        "semantic": ["topography", "landform", "climate", "hydrology", "river", "lake", "glacier", "groundwater", "soil", "vegetation", "ecosystem", "population", "city", "agriculture", "industry", "transportation", "region", "GIS", "remote sensing", "map", "coordinate", "projection"],
        "structure": ["要素-分布-规律结构", "数据-制图-分析结构", "区域-特征-比较结构"],
    },
    {
        "patterns": ["geology", "地质学", "岩石学", "矿物学", "构造地质", "地层学", "古生物"],
        "support": ["矿物", "岩石", "火成岩", "沉积岩", "变质岩", "晶体", "矿物学", "岩石学", "地层", "化石", "古生物", "构造", "断层", "褶皱", "节理", "板块", "地震", "火山", "岩浆", "矿床", "勘探"],
        "semantic": ["mineral", "rock", "igneous rock", "sedimentary rock", "metamorphic rock", "crystal", "mineralogy", "petrology", "stratum", "fossil", "paleontology", "structure", "fault", "fold", "joint", "plate", "earthquake", "volcano", "magma", "ore deposit", "exploration"],
        "structure": ["标本-鉴定-分类结构", "野外-观测-记录结构", "剖面-地层-解释结构"],
    },
    {
        "patterns": ["meteorology", "climatology", "气象学", "气候学", "天气", "大气", "降水", "台风", "锋面"],
        "support": ["大气", "气压", "温度", "湿度", "风", "云", "降水", "雨", "雪", "冰雹", "雾", "霾", "锋面", "气旋", "反气旋", "台风", "飓风", "龙卷风", "天气预报", "气候类型", "季风", "厄尔尼诺", "温室效应"],
        "semantic": ["atmosphere", "pressure", "temperature", "humidity", "wind", "cloud", "precipitation", "rain", "snow", "hail", "fog", "haze", "front", "cyclone", "anticyclone", "typhoon", "hurricane", "tornado", "weather forecast", "climate type", "monsoon", "El Nino", "greenhouse effect"],
        "structure": ["要素-过程-预报结构", "数据-模式-预测结构", "观测-分析-应用结构"],
    },
    {
        "patterns": ["oceanography", "marine science", "海洋学", "海洋科学", "海水", "潮汐", "洋流", "海洋生物"],
        "support": ["海水", "盐度", "温度", "密度", "潮汐", "潮流", "波浪", "洋流", "海流", "上升流", "温盐环流", "海底", "大陆架", "海沟", "珊瑚", "红树林", "海洋生态", "渔业", "海洋资源", "海洋污染", "海洋法"],
        "semantic": ["seawater", "salinity", "temperature", "density", "tide", "tidal current", "wave", "ocean current", "upwelling", "thermohaline circulation", "seafloor", "continental shelf", "trench", "coral", "mangrove", "marine ecology", "fishery", "marine resource", "marine pollution", "law of the sea"],
        "structure": ["要素-过程-分布结构", "观测-采样-分析结构", "资源-开发-保护结构"],
    },

    # ===== 天文与空间（3条） =====
    {
        "patterns": ["astronomy", "天文学", "观测", "望远镜", "恒星", "行星", "星系", "宇宙"],
        "support": ["恒星", "行星", "卫星", "彗星", "小行星", "星系", "银河系", "星云", "星团", "黑洞", "中子星", "白矮星", "红巨星", "超新星", "望远镜", "天文台", "观测", "星图", "天球", "坐标", "时区", "历法"],
        "semantic": ["star", "planet", "satellite", "comet", "asteroid", "galaxy", "Milky Way", "nebula", "star cluster", "black hole", "neutron star", "white dwarf", "red giant", "supernova", "telescope", "observatory", "observation", "star chart", "celestial sphere", "coordinate", "time zone", "calendar"],
        "structure": ["观测-记录-分析结构", "图像-处理-测量结构", "理论-模拟-验证结构"],
    },
    {
        "patterns": ["astrophysics", "天体物理", "宇宙学", "大爆炸", "暗物质", "暗能量", "引力波"],
        "support": ["光谱", "红移", "多普勒效应", "距离", "光度", "温度", "质量", "半径", "演化", "主序", "赫罗图", "宇宙学", "大爆炸", "宇宙微波背景", "暗物质", "暗能量", "引力波", "相对论", "黑洞", "吸积盘", "喷流"],
        "semantic": ["spectrum", "redshift", "Doppler effect", "distance", "luminosity", "temperature", "mass", "radius", "evolution", "main sequence", "HR diagram", "cosmology", "Big Bang", "CMB", "dark matter", "dark energy", "gravitational wave", "relativity", "black hole", "accretion disk", "jet"],
        "structure": ["观测-物理量-模型结构", "数据-拟合-推断结构", "理论-模拟-对比结构"],
    },
    {
        "patterns": ["aerospace", "astronautics", "航天", "宇航", "卫星", "火箭", "轨道", "空间站", "遥感", "GIS", "导航"],
        "support": ["火箭", "推进", "轨道", "卫星", "空间站", "载人航天", "深空探测", "着陆器", "巡视器", "遥感", "卫星图像", "GPS", "北斗", "导航", "GIS", "地理信息系统", "姿态控制", "再入", "热防护", "生命保障"],
        "semantic": ["rocket", "propulsion", "orbit", "satellite", "space station", "manned spaceflight", "deep space exploration", "lander", "rover", "remote sensing", "satellite image", "GPS", "BeiDou", "navigation", "GIS", "attitude control", "re-entry", "thermal protection", "life support"],
        "structure": ["轨道-力学-控制结构", "数据-处理-应用结构", "设计-仿真-验证结构"],
    },

    # ===== 农学林学（2条） =====
    {
        "patterns": ["agronomy", "crop science", "农学", "作物学", "栽培", "育种", "土壤肥料", "植物保护"],
        "support": ["作物", "品种", "栽培", "耕作", "播种", "施肥", "灌溉", "排水", "育种", "杂交", "选择", "诱变", "转基因", "种子", "发芽", "生长", "发育", "产量", "品质", "病虫害", "农药", "生物防治", "土壤", "肥料", "养分"],
        "semantic": ["crop", "variety", "cultivation", "tillage", "sowing", "fertilization", "irrigation", "drainage", "breeding", "hybridization", "selection", "mutation", "transgenic", "seed", "germination", "growth", "development", "yield", "quality", "pest", "pesticide", "biological control", "soil", "fertilizer", "nutrient"],
        "structure": ["品种-栽培-管理结构", "田间-观测-记录结构", "实验-分析-推广结构"],
    },
    {
        "patterns": ["forestry", "林学", "森林", "树木", "造林", "森林经理", "木材"],
        "support": ["森林", "树木", "树种", "造林", "抚育", "采伐", "更新", "森林经理", "调查", "蓄积", "生长量", "木材", "材性", "加工", "利用", "保护", "防火", "病虫害", "生态", "碳汇", "自然保护区"],
        "semantic": ["forest", "tree", "species", "afforestation", "tending", "logging", "regeneration", "forest management", "inventory", "volume", "growth", "timber", "wood property", "processing", "utilization", "protection", "fire prevention", "pest", "ecology", "carbon sink", "nature reserve"],
        "structure": ["调查-设计-经营结构", "样地-测量-计算结构", "保护-利用-可持续结构"],
    },

    # ===== 医学类（4条） =====
    {
        "patterns": ["anatomy", "histology", "解剖学", "组织学", "胚胎学", "系统解剖", "局部解剖", "断层解剖"],
        "support": ["骨骼", "肌肉", "关节", "神经", "血管", "内脏", "心脏", "肺", "肝", "肾", "脑", "脊髓", "感觉器", "皮肤", "细胞", "组织", "上皮", "结缔", "肌肉组织", "神经组织", "胚胎", "发育", "畸形"],
        "semantic": ["bone", "muscle", "joint", "nerve", "blood vessel", "viscera", "heart", "lung", "liver", "kidney", "brain", "spinal cord", "sense organ", "skin", "cell", "tissue", "epithelium", "connective tissue", "muscle tissue", "nervous tissue", "embryo", "development", "malformation"],
        "structure": ["系统-器官-结构结构", "标本-观察-绘图结构", "切片-染色-镜检结构"],
    },
    {
        "patterns": ["pathology", "pathophysiology", "病理学", "病理生理学", "病理解剖", "临床病理"],
        "support": ["细胞损伤", "适应", "萎缩", "肥大", "增生", "化生", "变性", "坏死", "凋亡", "炎症", "变质", "渗出", "修复", "纤维化", "瘢痕", "肿瘤", "良性", "恶性", "癌", "肉瘤", "转移", "心血管", "呼吸", "消化", "泌尿", "内分泌", "神经", "传染病"],
        "semantic": ["cell injury", "adaptation", "atrophy", "hypertrophy", "hyperplasia", "metaplasia", "degeneration", "necrosis", "apoptosis", "inflammation", "alteration", "exudation", "proliferation", "repair", "fibrosis", "scar", "tumor", "benign", "malignant", "carcinoma", "sarcoma", "metastasis", "cardiovascular", "respiratory", "digestive", "urinary", "endocrine", "neural", "infectious disease"],
        "structure": ["病变-机制-临床结构", "大体-镜下-诊断结构", "病因-发病-转归结构"],
    },
    {
        "patterns": ["pharmacology", "toxicology", "药理学", "毒理学", "药物化学", "药剂学", "临床药理"],
        "support": ["药物", "药效学", "药动学", "吸收", "分布", "代谢", "排泄", "ADME", "受体", "激动剂", "拮抗剂", "剂量", "浓度", "半衰期", "生物利用度", "毒性", "LD50", "ED50", "治疗指数", "不良反应", "副作用", "禁忌", "相互作用", "处方", "给药途径"],
        "semantic": ["drug", "pharmacodynamics", "pharmacokinetics", "absorption", "distribution", "metabolism", "excretion", "ADME", "receptor", "agonist", "antagonist", "dose", "concentration", "half-life", "bioavailability", "toxicity", "LD50", "ED50", "therapeutic index", "adverse reaction", "side effect", "contraindication", "interaction", "prescription", "route of administration"],
        "structure": ["药物-靶点-效应结构", "剂量-反应-毒性结构", "实验-数据-结论结构"],
    },
    {
        "patterns": ["immunology", "microbiology", "免疫学", "微生物学", "寄生虫学", "病原生物", "病毒学", "细菌学", "真菌学"],
        "support": ["免疫", "抗原", "抗体", "淋巴细胞", "T细胞", "B细胞", "NK细胞", "巨噬细胞", "树突状细胞", "MHC", "补体", "细胞因子", "过敏反应", "自身免疫", "免疫缺陷", "疫苗", "微生物", "细菌", "病毒", "真菌", "寄生虫", "培养", "染色", "鉴定", "消毒", "灭菌", "抗生素"],
        "semantic": ["immunity", "antigen", "antibody", "lymphocyte", "T cell", "B cell", "NK cell", "macrophage", "dendritic cell", "MHC", "complement", "cytokine", "allergy", "autoimmunity", "immunodeficiency", "vaccine", "microorganism", "bacteria", "virus", "fungus", "parasite", "culture", "staining", "identification", "disinfection", "sterilization", "antibiotic"],
        "structure": ["抗原-免疫应答-效应结构", "培养-鉴定-药敏结构", "实验-观察-结论结构"],
    },

    # ===== 计算机基础（4条） =====
    {
        "patterns": ["data structure", "algorithm", "数据结构", "算法", "leetcode", "排序", "查找", "树", "图", "动态规划", "贪心", "分治", "回溯", "复杂度"],
        "support": ["数组", "链表", "栈", "队列", "树", "二叉树", "AVL", "B树", "红黑树", "堆", "哈希表", "图", "DFS", "BFS", "Dijkstra", "排序", "快排", "归并", "动态规划", "贪心", "分治", "回溯", "递归", "迭代", "时间复杂度", "空间复杂度"],
        "semantic": ["array", "linked list", "stack", "queue", "tree", "binary tree", "AVL", "B-tree", "red-black tree", "heap", "hash table", "graph", "DFS", "BFS", "Dijkstra", "sorting", "quicksort", "mergesort", "DP", "greedy", "divide and conquer", "backtracking", "recursion", "iteration", "time complexity", "space complexity"],
        "structure": ["问题-思路-代码结构", "算法步骤-复杂度-优化结构", "数据结构-操作-应用结构"],
    },
    {
        "patterns": ["operating system", "OS", "操作系统", "进程", "线程", "内存管理", "虚拟内存", "文件系统", "死锁", "调度", "内核", "系统调用", "Linux内核"],
        "support": ["进程", "线程", "并发", "同步", "互斥", "信号量", "管程", "死锁", "银行家算法", "内存", "分页", "分段", "虚拟内存", "页面置换", "FIFO", "LRU", "文件系统", "inode", "磁盘调度", "进程调度", "优先级", "时间片", "内核", "系统调用", "中断", "trap"],
        "semantic": ["process", "thread", "concurrency", "synchronization", "mutual exclusion", "semaphore", "monitor", "deadlock", "banker's algorithm", "memory", "paging", "segmentation", "virtual memory", "page replacement", "FIFO", "LRU", "file system", "inode", "disk scheduling", "CPU scheduling", "priority", "time slice", "kernel", "system call", "interrupt", "trap"],
        "structure": ["概念-机制-算法结构", "资源-竞争-解决结构", "系统调用-内核-响应结构"],
    },
    {
        "patterns": ["computer network", "计算机网络", "TCP/IP", "HTTP", "路由", "交换", "网络安全", "socket", "DNS", "CDN", "负载均衡", "Wireshark"],
        "support": ["OSI模型", "TCP/IP", "HTTP", "HTTPS", "DNS", "DHCP", "NAT", "路由", "RIP", "OSPF", "BGP", "交换", "VLAN", "子网", "CIDR", "拥塞控制", "流量控制", "滑动窗口", "三次握手", "四次挥手", "socket", "负载均衡", "CDN", "防火墙", "VPN", "Wireshark", "抓包"],
        "semantic": ["OSI model", "TCP/IP", "HTTP", "HTTPS", "DNS", "DHCP", "NAT", "routing", "RIP", "OSPF", "BGP", "switching", "VLAN", "subnet", "CIDR", "congestion control", "flow control", "sliding window", "three-way handshake", "four-way wave", "socket", "load balancing", "CDN", "firewall", "VPN", "Wireshark", "packet capture"],
        "structure": ["协议层次-封装-传输结构", "网络拓扑-配置-测试结构", "请求-响应-分析结构"],
    },
    {
        "patterns": ["database", "数据库", "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "事务", "索引", "查询优化", "范式", "ER图", "NoSQL"],
        "support": ["表", "行", "列", "主键", "外键", "索引", "B+树", "事务", "ACID", "隔离级别", "锁", "死锁", "SQL", "SELECT", "JOIN", "子查询", "视图", "存储过程", "触发器", "范式", "ER图", "NoSQL", "MongoDB", "Redis", "缓存", "分片", "复制", "备份"],
        "semantic": ["table", "row", "column", "primary key", "foreign key", "index", "B+ tree", "transaction", "ACID", "isolation level", "lock", "deadlock", "SQL", "SELECT", "JOIN", "subquery", "view", "stored procedure", "trigger", "normalization", "ER diagram", "NoSQL", "MongoDB", "Redis", "cache", "sharding", "replication", "backup"],
        "structure": ["表结构-关系-查询结构", "ER图-范式-设计结构", "事务-并发-恢复结构"],
    },

    # ===== 编程开发（4条） =====
    {
        "patterns": ["Python", "python编程", "python开发", "脚本", "爬虫", "自动化", "数据分析", "数据科学", "pandas", "numpy"],
        "support": ["Python", "解释器", "pip", "虚拟环境", "模块", "包", "函数", "类", "装饰器", "生成器", "迭代器", "列表推导", "字典", "元组", "集合", "文件读写", "正则表达式", "多线程", "多进程", "异步", "async", "await", "爬虫", "requests", "BeautifulSoup", "Scrapy", "Selenium", "数据分析", "pandas", "numpy", "matplotlib", "Jupyter"],
        "semantic": ["Python", "interpreter", "pip", "virtualenv", "module", "package", "function", "class", "decorator", "generator", "iterator", "list comprehension", "dict", "tuple", "set", "file I/O", "regex", "multithreading", "multiprocessing", "asynchronous", "async", "await", "crawler", "requests", "BeautifulSoup", "Scrapy", "Selenium", "data analysis", "pandas", "numpy", "matplotlib", "Jupyter"],
        "structure": ["需求-代码-测试结构", "数据-处理-输出结构", "模块-接口-集成结构"],
    },
    {
        "patterns": ["Java", "java开发", "后端开发", "Spring", "Spring Boot", "微服务", "Maven", "Gradle", "JVM"],
        "support": ["Java", "JVM", "字节码", "类加载", "垃圾回收", "GC", "多线程", "并发", "锁", "synchronized", "volatile", "集合", "List", "Map", "Set", "Stream", "Lambda", "反射", "注解", "Spring", "Spring Boot", "Spring MVC", "MyBatis", "Hibernate", "REST", "JSON", "XML", "Maven", "Gradle", "Tomcat", "Nginx", "Redis", "Kafka", "RabbitMQ"],
        "semantic": ["Java", "JVM", "bytecode", "class loading", "garbage collection", "GC", "multithreading", "concurrency", "lock", "synchronized", "volatile", "collection", "List", "Map", "Set", "Stream", "Lambda", "reflection", "annotation", "Spring", "Spring Boot", "Spring MVC", "MyBatis", "Hibernate", "REST", "JSON", "XML", "Maven", "Gradle", "Tomcat", "Nginx", "Redis", "Kafka", "RabbitMQ"],
        "structure": ["接口-实现-测试结构", "配置-服务-调用结构", "模型-视图-控制器结构"],
    },
    {
        "patterns": ["frontend", "web前端", "前端开发", "HTML", "CSS", "JavaScript", "React", "Vue", "Angular", "TypeScript", "Node.js"],
        "support": ["HTML", "CSS", "JavaScript", "DOM", "BOM", "事件", "异步", "Promise", "async", "await", "ES6", "模块化", "webpack", "vite", "npm", "yarn", "React", "Vue", "Angular", "组件", "状态管理", "路由", "钩子", "TypeScript", "类型", "接口", "Node.js", "Express", "Koa", "HTTP", "AJAX", "Fetch", "跨域", "响应式", "移动端适配"],
        "semantic": ["HTML", "CSS", "JavaScript", "DOM", "BOM", "event", "asynchronous", "Promise", "async", "await", "ES6", "module", "webpack", "vite", "npm", "yarn", "React", "Vue", "Angular", "component", "state management", "router", "hook", "TypeScript", "type", "interface", "Node.js", "Express", "Koa", "HTTP", "AJAX", "Fetch", "CORS", "responsive", "mobile adaptation"],
        "structure": ["结构-样式-交互结构", "组件-状态-渲染结构", "请求-响应-更新结构"],
    },
    {
        "patterns": ["mobile development", "app开发", "Android", "iOS", "Flutter", "React Native", "Swift", "Kotlin", "小程序", "uni-app"],
        "support": ["Android", "iOS", "Flutter", "React Native", "Swift", "Kotlin", "Java", "Objective-C", "Dart", "Activity", "Fragment", "ViewController", "生命周期", "布局", "约束", "Widget", "状态管理", "路由", "导航", "网络请求", "本地存储", "推送", "定位", "相机", "传感器", "小程序", "微信", "支付宝", "uni-app", "混合开发"],
        "semantic": ["Android", "iOS", "Flutter", "React Native", "Swift", "Kotlin", "Java", "Objective-C", "Dart", "Activity", "Fragment", "ViewController", "lifecycle", "layout", "constraint", "Widget", "state management", "routing", "navigation", "network request", "local storage", "push notification", "location", "camera", "sensor", "mini program", "WeChat", "Alipay", "uni-app", "hybrid development"],
        "structure": ["页面-逻辑-数据结构", "组件-事件-状态结构", "请求-缓存-展示结构"],
    },

    # ===== 软件工程（4条） =====
    {
        "patterns": ["software engineering", "软件工程", "需求分析", "系统设计", "UML", "设计模式", "敏捷开发", "Scrum"],
        "support": ["需求", "用例", "UML", "类图", "时序图", "状态图", "设计模式", "单例", "工厂", "观察者", "策略", "MVC", "MVVM", "敏捷", "Scrum", "Sprint", "用户故事", "看板", "迭代", "重构", "技术债务", "代码审查", "版本控制", "Git", "分支", "合并"],
        "semantic": ["requirement", "use case", "UML", "class diagram", "sequence diagram", "state diagram", "design pattern", "singleton", "factory", "observer", "strategy", "MVC", "MVVM", "agile", "Scrum", "Sprint", "user story", "Kanban", "iteration", "refactoring", "technical debt", "code review", "version control", "Git", "branch", "merge"],
        "structure": ["需求-设计-实现结构", "模型-视图-控制器结构", "迭代-反馈-改进结构"],
    },
    {
        "patterns": ["DevOps", "CI/CD", "持续集成", "持续部署", "Jenkins", "GitLab CI", "Docker", "Kubernetes", "运维"],
        "support": ["DevOps", "CI/CD", "持续集成", "持续部署", "Jenkins", "GitLab CI", "GitHub Actions", "Travis", "CircleCI", "Docker", "容器", "镜像", "Dockerfile", "Compose", "Kubernetes", "K8s", "Pod", "Deployment", "Service", "Ingress", "Helm", "监控", "Prometheus", "Grafana", "日志", "ELK", "告警", "SLA", "自动化", "脚本", "Ansible", "Terraform", "IaC"],
        "semantic": ["DevOps", "CI/CD", "continuous integration", "continuous deployment", "Jenkins", "GitLab CI", "GitHub Actions", "Travis", "CircleCI", "Docker", "container", "image", "Dockerfile", "Compose", "Kubernetes", "K8s", "Pod", "Deployment", "Service", "Ingress", "Helm", "monitoring", "Prometheus", "Grafana", "logging", "ELK", "alerting", "SLA", "automation", "script", "Ansible", "Terraform", "IaC"],
        "structure": ["代码-构建-部署结构", "基础设施-配置-管理结构", "监控-告警-优化结构"],
    },
    {
        "patterns": ["software testing", "QA", "测试", "单元测试", "集成测试", "自动化测试", "性能测试", "Selenium", "JUnit", "pytest"],
        "support": ["测试", "单元测试", "集成测试", "系统测试", "验收测试", "回归测试", "冒烟测试", "性能测试", "压力测试", "负载测试", "稳定性测试", "安全测试", "渗透测试", "自动化测试", "手工测试", "黑盒", "白盒", "灰盒", "测试用例", "测试计划", "缺陷", "Bug", "禅道", "Jira", "Selenium", "JUnit", "pytest", "Mock", "Stub", "覆盖率", "CI"],
        "semantic": ["testing", "unit test", "integration test", "system test", "acceptance test", "regression test", "smoke test", "performance test", "stress test", "load test", "stability test", "security test", "penetration test", "automated test", "manual test", "black box", "white box", "gray box", "test case", "test plan", "defect", "Bug", "Selenium", "JUnit", "pytest", "Mock", "Stub", "coverage", "CI"],
        "structure": ["用例-执行-报告结构", "需求-覆盖-验证结构", "缺陷-跟踪-修复结构"],
    },
    {
        "patterns": ["software architecture", "系统架构", "微服务", "分布式系统", "高并发", "高可用", "中间件", "架构设计"],
        "support": ["架构", "单体", "微服务", "SOA", "分布式", "集群", "负载均衡", "一致性", "CAP", "BASE", "分片", "分区", "副本", "主从", "读写分离", "缓存", "消息队列", "Kafka", "RabbitMQ", "RocketMQ", "注册中心", "网关", "熔断", "限流", "降级", "链路追踪", "容器化", "云原生", "Serverless"],
        "semantic": ["architecture", "monolithic", "microservice", "SOA", "distributed", "cluster", "load balancing", "consistency", "CAP", "BASE", "sharding", "partitioning", "replica", "master-slave", "read-write splitting", "cache", "message queue", "Kafka", "RabbitMQ", "RocketMQ", "service registry", "gateway", "circuit breaker", "rate limiting", "degradation", "tracing", "containerization", "cloud native", "Serverless"],
        "structure": ["需求-架构-演进结构", "模块-接口-依赖结构", "问题-方案-验证结构"],
    },

    # ===== AI与数据（4条） =====
    {
        "patterns": ["machine learning", "deep learning", "AI", "人工智能", "机器学习", "深度学习", "神经网络", "CNN", "RNN", "Transformer", "PyTorch", "TensorFlow", "训练", "模型"],
        "support": ["神经网络", "CNN", "RNN", "LSTM", "GRU", "Transformer", "注意力", "self-attention", "BERT", "GPT", "ResNet", "GAN", "VAE", "强化学习", "监督学习", "无监督学习", "迁移学习", "微调", "训练", "验证", "测试", "损失函数", "优化器", "Adam", "SGD", "学习率", "batch", "epoch", "过拟合", "欠拟合", "正则化", "Dropout", "归一化", "PyTorch", "TensorFlow", "Keras", "HuggingFace"],
        "semantic": ["neural network", "CNN", "RNN", "LSTM", "GRU", "Transformer", "attention", "self-attention", "BERT", "GPT", "ResNet", "GAN", "VAE", "RL", "supervised learning", "unsupervised learning", "transfer learning", "fine-tuning", "training", "validation", "test", "loss function", "optimizer", "Adam", "SGD", "learning rate", "batch", "epoch", "overfitting", "underfitting", "regularization", "Dropout", "normalization", "PyTorch", "TensorFlow", "Keras"],
        "structure": ["数据-模型-训练结构", "输入-网络-输出结构", "实验-指标-对比结构"],
    },
    {
        "patterns": ["data science", "data analysis", "数据科学", "数据分析", "数据挖掘", "商业智能", "BI", "大数据", "Hadoop", "Spark", "SQL分析"],
        "support": ["数据", "数据集", "DataFrame", "清洗", "预处理", "特征工程", "特征选择", "降维", "PCA", "可视化", "统计", "描述统计", "推断统计", "假设检验", "回归", "分类", "聚类", "时间序列", "A/B测试", "商业智能", "BI", "报表", "仪表盘", "大数据", "Hadoop", "Spark", "Hive", "Flink", "ETL", "数据仓库", "数据湖"],
        "semantic": ["data", "dataset", "DataFrame", "cleaning", "preprocessing", "feature engineering", "feature selection", "dimensionality reduction", "PCA", "visualization", "statistics", "descriptive statistics", "inferential statistics", "hypothesis test", "regression", "classification", "clustering", "time series", "A/B test", "business intelligence", "BI", "report", "dashboard", "big data", "Hadoop", "Spark", "Hive", "Flink", "ETL", "data warehouse", "data lake"],
        "structure": ["数据-清洗-分析结构", "特征-模型-评估结构", "指标-可视化-决策结构"],
    },
    {
        "patterns": ["computer vision", "CV", "NLP", "自然语言处理", "计算机视觉", "图像处理", "OpenCV", "OpenGL", "渲染", "目标检测", "语义分割", "OCR", "大模型", "LLM"],
        "support": ["图像", "视频", "像素", "滤波", "边缘检测", "特征提取", "SIFT", "HOG", "目标检测", "YOLO", "Faster R-CNN", "语义分割", "实例分割", "OCR", "人脸识别", "姿态估计", "三维重建", "渲染", "光栅化", "光线追踪", "NLP", "分词", "词性标注", "命名实体识别", "句法分析", "机器翻译", "文本分类", "情感分析", "问答", "摘要", "大模型", "LLM", "prompt engineering", "RAG", "fine-tuning"],
        "semantic": ["image", "video", "pixel", "filter", "edge detection", "feature extraction", "SIFT", "HOG", "object detection", "YOLO", "Faster R-CNN", "semantic segmentation", "instance segmentation", "OCR", "face recognition", "pose estimation", "3D reconstruction", "rendering", "rasterization", "ray tracing", "NLP", "tokenization", "POS tagging", "NER", "parsing", "machine translation", "text classification", "sentiment analysis", "QA", "summarization", "LLM", "prompt engineering", "RAG", "fine-tuning"],
        "structure": ["图像-特征-识别结构", "文本-编码-解码结构", "输入-模型-输出结构"],
    },
    {
        "patterns": ["cybersecurity", "cryptography", "信息安全", "密码学", "网络安全", "渗透测试", "漏洞", "加密", "解密", "RSA", "AES", "区块链"],
        "support": ["加密", "解密", "对称加密", "非对称加密", "RSA", "AES", "DES", "哈希", "MD5", "SHA", "数字签名", "证书", "PKI", "TLS", "SSL", "HTTPS", "VPN", "防火墙", "IDS", "IPS", "入侵检测", "渗透测试", "漏洞", "SQL注入", "XSS", "CSRF", "DDoS", "区块链", "比特币", "智能合约", "零知识证明"],
        "semantic": ["encryption", "decryption", "symmetric", "asymmetric", "RSA", "AES", "DES", "hash", "MD5", "SHA", "digital signature", "certificate", "PKI", "TLS", "SSL", "HTTPS", "VPN", "firewall", "IDS", "IPS", "intrusion detection", "penetration test", "vulnerability", "SQL injection", "XSS", "CSRF", "DDoS", "blockchain", "Bitcoin", "smart contract", "zero-knowledge proof"],
        "structure": ["明文-算法-密文结构", "攻击-防御-测试结构", "协议-握手-通信结构"],
    },

    # ===== 电子与通信（4条） =====
    {
        "patterns": ["circuit", "electronic", "电路", "模拟电路", "数字电路", "电子线路", "CMOS", "TTL", "运放", "滤波器", "振荡器"],
        "support": ["电阻", "电容", "电感", "二极管", "三极管", "MOSFET", "运放", "反馈", "增益", "带宽", "截止频率", "谐振", "滤波器", "振荡器", "整流", "稳压", "逻辑门", "触发器", "计数器", "译码器", "AD", "DA", "采样", "量化"],
        "semantic": ["resistor", "capacitor", "inductor", "diode", "transistor", "MOSFET", "op-amp", "feedback", "gain", "bandwidth", "cutoff frequency", "resonance", "filter", "oscillator", "rectifier", "regulator", "logic gate", "flip-flop", "counter", "decoder", "ADC", "DAC", "sampling", "quantization"],
        "structure": ["电路图-分析-计算结构", "模块-参数-仿真结构", "原理-设计-调试结构"],
    },
    {
        "patterns": ["signal processing", "communication", "信号与系统", "信号处理", "通信原理", "调制", "解调", "编码", "信道"],
        "support": ["信号", "系统", "卷积", "Fourier变换", "Laplace变换", "Z变换", "采样定理", "滤波", "调制", "解调", "编码", "信道", "噪声", "误码率", "多路复用", "FDM", "TDMA", "CDMA", "OFDM", "扩频", "同步", "均衡", "天线", "传播", "衰落", "多径"],
        "semantic": ["signal", "system", "convolution", "Fourier transform", "Laplace transform", "Z-transform", "sampling theorem", "filtering", "modulation", "demodulation", "encoding", "channel", "noise", "BER", "multiplexing", "FDM", "TDMA", "CDMA", "OFDM", "spread spectrum", "synchronization", "equalization", "antenna", "propagation", "fading", "multipath"],
        "structure": ["信号-变换-频谱结构", "系统-响应-稳定性结构", "发送-信道-接收结构"],
    },
    {
        "patterns": ["microcontroller", "embedded system", "FPGA", "单片机", "微机原理", "嵌入式系统", "ARM", "STM32", "Verilog", "VHDL"],
        "support": ["寄存器", "中断", "定时器", "计数器", "ADC", "DAC", "GPIO", "UART", "SPI", "I2C", "PWM", "DMA", "中断向量", "时钟", "复位", "存储器映射", "流水线", "Verilog", "VHDL", "综合", "布局布线", "时序约束", "逻辑分析仪", "示波器"],
        "semantic": ["register", "interrupt", "timer", "counter", "ADC", "DAC", "GPIO", "UART", "SPI", "I2C", "PWM", "DMA", "interrupt vector", "clock", "reset", "memory map", "pipeline", "Verilog", "VHDL", "synthesis", "place and route", "timing constraint", "logic analyzer", "oscilloscope"],
        "structure": ["硬件-寄存器-代码结构", "模块-接口-时序结构", "状态机-转换-输出结构"],
    },
    {
        "patterns": ["telecommunication", "wireless", "通信工程", "移动通信", "5G", "4G", "LTE", "WiFi", "蓝牙", "射频", "RF"],
        "support": ["基站", "小区", "切换", "漫游", "频谱", "带宽", "载波", "多址", "FDMA", "TDMA", "CDMA", "OFDMA", "MIMO", "波束成形", "信道容量", "香农定理", "5G", "NR", "4G", "LTE", "WiFi", "802.11", "蓝牙", "ZigBee", "LoRa", "NB-IoT", "射频", "功放", "低噪放", "混频", "本振"],
        "semantic": ["base station", "cell", "handover", "roaming", "spectrum", "bandwidth", "carrier", "multiple access", "FDMA", "TDMA", "CDMA", "OFDMA", "MIMO", "beamforming", "channel capacity", "Shannon theorem", "5G", "NR", "4G", "LTE", "WiFi", "802.11", "Bluetooth", "ZigBee", "LoRa", "NB-IoT", "RF", "power amplifier", "LNA", "mixer", "local oscillator"],
        "structure": ["信源-信道-信宿结构", "协议-帧-传输结构", "网络-优化-测试结构"],
    },

    # ===== 机械与材料（1条） =====
    {
        "patterns": ["mechanical engineering", "mechanical design", "机械工程", "机械设计", "机械原理", "机构学", "CAD/CAM", "SolidWorks", "ANSYS"],
        "support": ["机构", "连杆", "凸轮", "齿轮", "轴承", "轴", "联轴器", "弹簧", "螺栓", "焊接", "应力", "应变", "变形", "疲劳", "有限元", "网格", "边界条件", "模态分析", "热分析", "优化设计", "公差", "配合", "制图", "三视图", "装配图"],
        "semantic": ["mechanism", "linkage", "cam", "gear", "bearing", "shaft", "coupling", "spring", "bolt", "welding", "stress", "strain", "deformation", "fatigue", "finite element", "mesh", "boundary condition", "modal analysis", "thermal analysis", "optimization", "tolerance", "fit", "drafting", "orthographic", "assembly drawing"],
        "structure": ["零件-装配-工程图结构", "载荷-约束-求解结构", "设计-校核-优化结构"],
    },

    # ===== 机械与材料（3条） =====
    {
        "patterns": ["material mechanics", "材料力学", "固体力学", "弹性力学", "塑性力学", "断裂力学", "材料强度"],
        "support": ["应力", "应变", "位移", "变形", "弹性", "塑性", "屈服", "强度", "刚度", "稳定性", "疲劳", "蠕变", "断裂", "韧性", "硬度", "冲击", "扭转", "弯曲", "剪切", "拉伸", "压缩", "胡克定律", "Mohr圆", "有限元"],
        "semantic": ["stress", "strain", "displacement", "deformation", "elasticity", "plasticity", "yield", "strength", "stiffness", "stability", "fatigue", "creep", "fracture", "toughness", "hardness", "impact", "torsion", "bending", "shear", "tension", "compression", "Hooke's law", "Mohr circle", "finite element"],
        "structure": ["受力-变形-强度结构", "模型-求解-验证结构", "实验-数据-拟合结构"],
    },
    {
        "patterns": ["materials science", "材料科学", "纳米技术", "高分子", "陶瓷", "冶金", "晶体", "晶格", "缺陷", "相图"],
        "support": ["晶体", "晶格", "晶胞", "Miller指数", "缺陷", "位错", "扩散", "相图", "相变", "合金", "钢", "陶瓷", "高分子", "聚合物", "纳米材料", "复合材料", "半导体", "能带", "X射线衍射", "SEM", "TEM", "热处理", "淬火", "回火", "退火"],
        "semantic": ["crystal", "lattice", "unit cell", "Miller index", "defect", "dislocation", "diffusion", "phase diagram", "phase transition", "alloy", "steel", "ceramic", "polymer", "nanomaterial", "composite", "semiconductor", "band structure", "XRD", "SEM", "TEM", "heat treatment", "quenching", "tempering", "annealing"],
        "structure": ["结构-性能-应用结构", "制备-表征-测试结构", "相图-工艺-组织结构"],
    },
    {
        "patterns": ["manufacturing", "机械加工", "制造工艺", "CNC", "3D打印", "注塑", "钣金", "焊接", "铸造", "锻造"],
        "support": ["车削", "铣削", "钻削", "磨削", "CNC", "数控", "刀具", "夹具", "公差", "表面粗糙度", "3D打印", "增材制造", "SLA", "FDM", "SLS", "注塑", "模具", "钣金", "冲压", "折弯", "焊接", "电弧焊", "激光焊", "铸造", "砂型", "熔模", "锻造", "轧制", "挤压", "拉拔", "热处理", "装配", "检测"],
        "semantic": ["turning", "milling", "drilling", "grinding", "CNC", "numerical control", "cutting tool", "fixture", "tolerance", "surface roughness", "3D printing", "additive manufacturing", "SLA", "FDM", "SLS", "injection molding", "mold", "sheet metal", "stamping", "bending", "welding", "arc welding", "laser welding", "casting", "sand mold", "investment casting", "forging", "rolling", "extrusion", "drawing", "heat treatment", "assembly", "inspection"],
        "structure": ["工艺-参数-质量控制结构", "设计-制造-检测结构", "材料-加工-性能结构"],
    },

    # ===== 土木建筑（4条） =====
    {
        "patterns": ["civil engineering", "structural engineering", "土木工程", "结构工程", "土力学", "基础工程", "混凝土", "钢结构", "桥梁", "隧道", "岩土", "BIM", "PKPM"],
        "support": ["混凝土", "钢筋", "钢结构", "砌体", "木材", "地基", "基础", "桩", "挡土墙", "边坡", "梁", "柱", "板", "节点", "内力", "配筋", "挠度", "裂缝", "抗震", "荷载", "BIM", "PKPM", "ETABS", "MIDAS"],
        "semantic": ["concrete", "rebar", "steel structure", "masonry", "timber", "foundation", "pile", "retaining wall", "slope", "beam", "column", "slab", "joint", "internal force", "reinforcement", "deflection", "crack", "seismic", "load", "BIM", "PKPM", "ETABS", "MIDAS"],
        "structure": ["结构-荷载-内力结构", "构件-配筋-验算结构", "模型-分析-结果结构"],
    },
    {
        "patterns": ["architecture", "建筑学", "建筑设计", "建筑历史", "建筑技术", "绿色建筑", "参数化设计", "Rhino", "Grasshopper"],
        "support": ["建筑", "空间", "形式", "功能", "结构", "材料", "构造", "节点", "立面", "平面", "剖面", "总平面", "场地", "流线", "采光", "通风", "保温", "隔热", "节能", "可持续", "绿色建筑", "LEED", "BIM", "参数化", "生成设计", "Rhino", "Grasshopper", "Revit"],
        "semantic": ["architecture", "space", "form", "function", "structure", "material", "construction", "joint", "facade", "plan", "section", "site plan", "site", "circulation", "daylighting", "ventilation", "insulation", "thermal", "energy saving", "sustainable", "green building", "LEED", "BIM", "parametric", "generative design", "Rhino", "Grasshopper", "Revit"],
        "structure": ["概念-方案-深化结构", "功能-流线-空间结构", "图纸-模型-表达结构"],
    },
    {
        "patterns": ["geotechnical engineering", "岩土工程", "地基基础", "边坡工程", "地下工程", "基坑", "隧道工程"],
        "support": ["土", "岩石", "地基", "基础", "桩", "筏板", "箱基", "边坡", "支护", "锚杆", "土钉", "挡土墙", "基坑", "降水", "回灌", "隧道", "盾构", "TBM", "新奥法", "监控量测", "沉降", "位移", "应力", "孔隙水压力", "渗透", "液化", "固结", "三轴试验", "直剪试验"],
        "semantic": ["soil", "rock", "foundation", "pile", "raft", "box foundation", "slope", "support", "anchor", "soil nail", "retaining wall", "excavation", "dewatering", "recharge", "tunnel", "shield", "TBM", "NATM", "monitoring", "settlement", "displacement", "stress", "pore water pressure", "seepage", "liquefaction", "consolidation", "triaxial test", "direct shear test"],
        "structure": ["地质-设计-施工结构", "监测-分析-反馈结构", "试验-参数-模拟结构"],
    },
    {
        "patterns": ["BIM", "CAD制图", "建筑CAD", "结构CAD", "Revit", "AutoCAD", "天正", "PKPM", "ETABS", "SAP2000", "Midas"],
        "support": ["CAD", "图层", "线型", "标注", "比例", "图纸空间", "模型空间", "块", "属性", "动态块", "参数化", "约束", "BIM", "族", "体量", "视图", "明细表", "碰撞检查", "Navisworks", "渲染", "出图", "PKPM", "建模", "荷载", "计算", "配筋", "施工图", "详图", "节点大样"],
        "semantic": ["CAD", "layer", "linetype", "dimension", "scale", "paper space", "model space", "block", "attribute", "dynamic block", "parametric", "constraint", "BIM", "family", "mass", "view", "schedule", "clash detection", "Navisworks", "rendering", "plotting", "PKPM", "modeling", "load", "calculation", "reinforcement", "construction drawing", "detail drawing", "joint detail"],
        "structure": ["建模-分析-出图结构", "平面-立面-剖面结构", "冲突-协调-优化结构"],
    },

    # ===== 能源与环境（4条） =====
    {
        "patterns": ["power system", "power electronics", "能源", "电力系统", "电力电子", "发电机", "变压器", "输电", "配电", "智能电网"],
        "support": ["发电机", "变压器", "输电线路", "配电网络", "负荷", "潮流计算", "短路计算", "稳定性", "继电保护", "逆变器", "整流器", "DC-DC", "AC-DC", "PWM控制", "光伏", "风电", "储能", "电池", "燃料电池", "智能电网", "微电网", "无功补偿", "谐波"],
        "semantic": ["generator", "transformer", "transmission line", "distribution network", "load", "power flow", "short circuit", "stability", "relay protection", "inverter", "rectifier", "DC-DC", "AC-DC", "PWM control", "PV", "wind power", "energy storage", "battery", "fuel cell", "smart grid", "microgrid", "reactive power compensation", "harmonic"],
        "structure": ["电源-变换-负载结构", "系统-计算-保护结构", "资源-转换-并网结构"],
    },
    {
        "patterns": ["new energy", "renewable energy", "新能源", "可再生能源", "光伏", "太阳能", "风电", "核能", "氢能", "生物质能"],
        "support": ["光伏", "太阳能电池", "组件", "逆变器", "MPPT", "风电", "风机", "叶片", "齿轮箱", "发电机", "核能", "反应堆", "裂变", "聚变", "核燃料", "氢能", "电解水", "燃料电池", "储氢", "生物质", "沼气", "生物柴油", "地热能", "潮汐能", "波浪能", "储能", "锂电池", "钠电池", "液流电池", "超级电容", "抽水蓄能", "压缩空气"],
        "semantic": ["PV", "solar cell", "module", "inverter", "MPPT", "wind power", "turbine", "blade", "gearbox", "generator", "nuclear", "reactor", "fission", "fusion", "nuclear fuel", "hydrogen", "electrolysis", "fuel cell", "hydrogen storage", "biomass", "biogas", "biodiesel", "geothermal", "tidal", "wave", "energy storage", "lithium battery", "sodium battery", "flow battery", "supercapacitor", "pumped hydro", "compressed air"],
        "structure": ["资源-转换-存储结构", "系统设计-优化-运行结构", "经济-环境-政策结构"],
    },
    {
        "patterns": ["environmental engineering", "环境工程", "水处理", "大气污染控制", "固废处理", "环境科学", "生态修复"],
        "support": ["水", "污水", "废水", "给水处理", "污水处理", "物理处理", "化学处理", "生物处理", "活性污泥", "生物膜", "膜处理", "反渗透", "超滤", "大气", "颗粒物", "SO2", "NOx", "VOCs", "脱硫", "脱硝", "除尘", "催化", "固废", "垃圾", "焚烧", "填埋", "堆肥", "资源化", "危废", "土壤", "地下水", "修复", "生态", "环评", "环境监测", "ISO14001"],
        "semantic": ["water", "sewage", "wastewater", "water treatment", "physical treatment", "chemical treatment", "biological treatment", "activated sludge", "biofilm", "membrane", "RO", "UF", "atmosphere", "PM", "SO2", "NOx", "VOCs", "desulfurization", "denitrification", "dedusting", "catalysis", "solid waste", "garbage", "incineration", "landfill", "composting", "recycling", "hazardous waste", "soil", "groundwater", "remediation", "ecology", "EIA", "environmental monitoring", "ISO14001"],
        "structure": ["污染物-工艺-去除结构", "监测-评价-控制结构", "设计-运行-优化结构"],
    },
    {
        "patterns": ["chemical engineering", "化工原理", "化学反应工程", "分离工程", "过程控制", "化工设计", " Aspen", "HYSYS"],
        "support": ["流体流动", "传热", "传质", "反应", "蒸馏", "吸收", "萃取", "结晶", "干燥", "过滤", "沉降", "离心", "混合", "搅拌", "反应器", "CSTR", "PFR", "催化剂", "动力学", "平衡", "转化率", "选择性", "收率", "物料衡算", "能量衡算", "流程模拟", "Aspen", "HYSYS", "PID", "控制", "安全", "HAZOP"],
        "semantic": ["fluid flow", "heat transfer", "mass transfer", "reaction", "distillation", "absorption", "extraction", "crystallization", "drying", "filtration", "sedimentation", "centrifugation", "mixing", "stirring", "reactor", "CSTR", "PFR", "catalyst", "kinetics", "equilibrium", "conversion", "selectivity", "yield", "material balance", "energy balance", "process simulation", "Aspen", "HYSYS", "PID", "control", "safety", "HAZOP"],
        "structure": ["单元操作-设计-计算结构", "流程-模拟-优化结构", "反应-分离-控制结构"],
    },

    # ===== 交通与车辆（4条） =====
    {
        "patterns": ["vehicle engineering", "automotive", "车辆工程", "汽车工程", "内燃机", "新能源汽车", "自动驾驶", "汽车设计"],
        "support": ["发动机", "内燃机", "汽油机", "柴油机", "电动机", "电池", "电机", "电控", "底盘", "悬架", "转向", "制动", "传动", "车身", "空气动力学", "NVH", "碰撞", "安全", "排放", "标定", "CAN", "LIN", "自动驾驶", "ADAS", "感知", "决策", "控制", "路径规划", "车联网", "V2X", "充电桩"],
        "semantic": ["engine", "ICE", "gasoline engine", "diesel engine", "electric motor", "battery", "motor", "controller", "chassis", "suspension", "steering", "braking", "transmission", "body", "aerodynamics", "NVH", "crash", "safety", "emission", "calibration", "CAN", "LIN", "autonomous driving", "ADAS", "perception", "decision", "control", "path planning", "V2X", "charging pile"],
        "structure": ["系统-部件-性能结构", "设计-仿真-试验结构", "感知-决策-执行结构"],
    },
    {
        "patterns": ["transportation", "交通工程", "交通运输", "交通规划", "交通流", "智能交通", "ITS"],
        "support": ["交通", "道路", "公路", "铁路", "水运", "航空", "管道", "运输", "物流", "客流", "货流", "OD", "交通流", "通行能力", "饱和度", "延误", "排队", "信号控制", "绿波", "协调", "智能交通", "ITS", "监控", "收费", "ETC", "导航", "调度", "优化", "路径规划", "多式联运"],
        "semantic": ["traffic", "road", "highway", "railway", "waterway", "aviation", "pipeline", "transport", "logistics", "passenger flow", "freight flow", "OD", "traffic flow", "capacity", "saturation", "delay", "queue", "signal control", "green wave", "coordination", "ITS", "monitoring", "toll", "ETC", "navigation", "dispatch", "optimization", "route planning", "multimodal transport"],
        "structure": ["需求-网络-流结构", "调查-分析-预测结构", "规划-设计-评估结构"],
    },
    {
        "patterns": ["road and bridge", "道路工程", "桥梁工程", "隧道工程", "路基", "路面", "沥青", "水泥混凝土"],
        "support": ["道路", "公路", "城市道路", "高速公路", "路基", "路面", "基层", "面层", "沥青", "水泥混凝土", "沥青混凝土", "柔性路面", "刚性路面", "桥梁", "梁桥", "拱桥", "斜拉桥", "悬索桥", "桥墩", "桥台", "基础", "支座", "伸缩缝", "预应力", "隧道", "衬砌", "掘进", "通风", "照明", "排水", "交通安全", "标志", "标线", "护栏"],
        "semantic": ["road", "highway", "urban road", "expressway", "subgrade", "pavement", "base", "surface", "asphalt", "cement concrete", "asphalt concrete", "flexible pavement", "rigid pavement", "bridge", "beam bridge", "arch bridge", "cable-stayed bridge", "suspension bridge", "pier", "abutment", "foundation", "bearing", "expansion joint", "prestress", "tunnel", "lining", "excavation", "ventilation", "lighting", "drainage", "traffic safety", "sign", "marking", "guardrail"],
        "structure": ["路线-路基-路面结构", "上部-下部-基础结构", "设计-施工-养护结构"],
    },
    {
        "patterns": ["aerospace", "aeronautics", "marine engineering", "航空航天", "航海", "船舶", "轮机", "飞行器设计"],
        "support": ["飞机", "飞行器", "机翼", "机身", "尾翼", "起落架", "发动机", "涡轮", "螺旋桨", "空气动力学", "升力", "阻力", "推力", "操纵性", "稳定性", "导航", "制导", "控制", "卫星", "轨道", "火箭", "飞船", "船舶", "船体", "轮机", "推进", "阻力", "浮力", "稳性", "摇摆", "耐波性", "操纵性", "港口", "航道", "锚泊", "系泊"],
        "semantic": ["aircraft", "airplane", "wing", "fuselage", "tail", "landing gear", "engine", "turbine", "propeller", "aerodynamics", "lift", "drag", "thrust", "controllability", "stability", "navigation", "guidance", "control", "satellite", "orbit", "rocket", "spacecraft", "ship", "hull", "marine engine", "propulsion", "resistance", "buoyancy", "stability", "rolling", "seakeeping", "maneuverability", "port", "channel", "anchoring", "mooring"],
        "structure": ["总体-气动-结构结构", "推进-控制-航电结构", "船体-轮机-电气结构"],
    },

    # ===== 测绘与矿业（4条） =====
    {
        "patterns": ["surveying", "测绘工程", "工程测量", "大地测量", "摄影测量", "遥感", "GIS", "GPS", "北斗"],
        "support": ["测量", "水准", "角度", "距离", "坐标", "高程", "控制网", "导线", "三角", "GNSS", "GPS", "北斗", "RTK", "全站仪", "水准仪", "摄影测量", "航空摄影", "倾斜摄影", "LiDAR", "点云", "遥感", "卫星影像", "InSAR", "GIS", "空间分析", "地图", "制图", "地籍", "房产", "变形监测", "精密工程测量"],
        "semantic": ["surveying", "leveling", "angle", "distance", "coordinate", "elevation", "control network", "traversing", "triangulation", "GNSS", "GPS", "BeiDou", "RTK", "total station", "level", "photogrammetry", "aerial photography", "oblique photography", "LiDAR", "point cloud", "remote sensing", "satellite image", "InSAR", "GIS", "spatial analysis", "map", "cartography", "cadastre", "property", "deformation monitoring", "precision engineering survey"],
        "structure": ["控制-碎部-成图结构", "数据-处理-分析结构", "监测-预警-评估结构"],
    },
    {
        "patterns": ["mining engineering", "矿业工程", "采矿", "矿物加工", "选矿", "矿山安全"],
        "support": ["矿床", "矿石", "岩石", "露天开采", "地下开采", "井巷", "掘进", "爆破", "支护", "通风", "排水", "提升", "运输", "充填", "尾矿", "选矿", "破碎", "磨矿", "浮选", "磁选", "重选", "浸出", "冶炼", "矿山安全", "瓦斯", "粉尘", "通风", "监测", "边坡", "塌陷"],
        "semantic": ["deposit", "ore", "rock", "open-pit mining", "underground mining", "shaft", "tunneling", "blasting", "support", "ventilation", "drainage", "hoisting", "transport", "backfill", "tailings", "mineral processing", "crushing", "grinding", "flotation", "magnetic separation", "gravity separation", "leaching", "smelting", "mine safety", "gas", "dust", "monitoring", "slope", "subsidence"],
        "structure": ["地质-开采-加工结构", "设计-施工-安全结构", "试验-优化-生产结构"],
    },
    {
        "patterns": ["petroleum engineering", "石油工程", "油气储运", "钻井", "采油", "油藏工程"],
        "support": ["石油", "天然气", "油藏", "气藏", "储层", "孔隙度", "渗透率", "饱和度", "钻井", "井身结构", "钻头", "泥浆", "固井", "完井", "射孔", "压裂", "酸化", "采油", "举升", "抽油机", "电潜泵", "气举", "注水", "三次采油", "聚合物驱", "油气集输", "管道", "储罐", "炼油", "化工"],
        "semantic": ["petroleum", "natural gas", "reservoir", "porosity", "permeability", "saturation", "drilling", "well structure", "bit", "mud", "cementing", "completion", "perforation", "fracturing", "acidizing", "production", "lifting", "pumpjack", "ESP", "gas lift", "water flooding", "EOR", "polymer flooding", "gathering", "pipeline", "tank", "refining", "petrochemical"],
        "structure": ["地质-钻井-开采结构", "油藏-工程-经济结构", "集输-处理-储运结构"],
    },
    {
        "patterns": ["safety engineering", "安全工程", "工业安全", "职业健康", "应急管理", "消防工程"],
        "support": ["安全", "危险源", "风险", "辨识", "评估", "控制", "事故", "预防", "应急救援", "预案", "演练", "消防", "防火", "灭火", "疏散", "防爆", "防尘", "防毒", "噪声", "振动", "辐射", "高温", "职业健康", "职业病", "个体防护", "PPE", "安全文化", "管理体系", "ISO45001"],
        "semantic": ["safety", "hazard", "risk", "identification", "assessment", "control", "accident", "prevention", "emergency response", "plan", "drill", "firefighting", "fire prevention", "extinguishing", "evacuation", "explosion protection", "dust control", "toxic control", "noise", "vibration", "radiation", "high temperature", "occupational health", "occupational disease", "PPE", "safety culture", "management system", "ISO45001"],
        "structure": ["辨识-评估-控制结构", "预防-应急-恢复结构", "制度-培训-文化结构"],
    },

    # ===== 英语与语言（4条） =====
    {
        "patterns": ["CET-4", "CET-6", "CET4", "CET6", "四六级", "英语四级", "英语六级", "大学英语", "College English Test"],
        "support": ["听力", "阅读", "翻译", "写作", "选词填空", "长篇阅读", "仔细阅读", "作文", "模板", "高频词汇", "真题", "模拟题", "考试时间", "答题卡", "分数"],
        "semantic": ["listening comprehension", "reading comprehension", "translation", "writing", "cloze", "long reading", "careful reading", "essay", "template", "high-frequency vocabulary", "past paper", "mock test", "exam time", "answer sheet", "score"],
        "structure": ["题目-选项-解析结构", "范文-模板-仿写结构", "听力原文-问题-答案结构"],
    },
    {
        "patterns": ["TOEFL", "IELTS", "GRE", "GMAT", "SAT", "托福", "雅思", "留学英语", "出国考试", "雅思口语", "雅思写作", "托福听力", "GRE词汇", "GRE数学"],
        "support": ["听力", "阅读", "口语", "写作", "综合写作", "独立写作", "Task1", "Task2", "口语题库", "机经", "TPO", "Cambridge", "词汇", "长难句", "同义替换", "逻辑", "Argument", "Issue", "Quantitative", "Verbal"],
        "semantic": ["TOEFL", "IELTS", "GRE", "GMAT", "SAT", "listening", "reading", "speaking", "writing", "integrated writing", "independent writing", "Task 1", "Task 2", "speaking pool", "prediction", "TPO", "Cambridge", "vocabulary", "complex sentence", "paraphrase", "logic", "Argument", "Issue", "Quantitative", "Verbal"],
        "structure": ["题目-范文-评分标准结构", "听力-笔记-答题结构", "阅读-定位-解析结构"],
    },
    {
        "patterns": ["English listening", "English speaking", "英语听力", "英语口语", "精听", "泛听", "dictation", "听写", "shadowing", "跟读", "发音", "音标", "VOA", "BBC", "TED", "播客", "podcast"],
        "support": ["精听", "泛听", "听写", "关键词", "主旨", "细节", "推理", "同义替换", "连读", "弱读", "口音", "语速", "笔记", "反复听", "字幕", "发音", "音标", "连读", "弱读", "语调", "重音", "节奏", "流利度", "地道表达"],
        "semantic": ["intensive listening", "extensive listening", "dictation", "key word", "main idea", "detail", "inference", "paraphrase", "liaison", "weak form", "accent", "speech rate", "note-taking", "repeated listening", "subtitle", "pronunciation", "phonetic symbol", "intonation", "stress", "rhythm", "fluency", "authentic expression"],
        "structure": ["音频-问题-选项结构", "听写-校对-总结结构", "话题-准备-表达结构"],
    },
    {
        "patterns": ["English reading", "English writing", "英语阅读", "英语写作", "英文原著", "外刊", "The Economist", "学术写作", "essay", "paper writing", "英文论文", "SCI写作", "creative writing"],
        "support": ["主旨", "细节", "推理", "词义猜测", "长难句", "语法分析", "段落结构", "逻辑关系", "同义替换", "关键词定位", "扫读", "略读", "笔记", "摘要", "批注", "主题句", "论点", "论据", "论证", "段落结构", "衔接", "过渡", "引用", "paraphrase", "总结", "引言", "结论", "参考文献", "APA", "MLA", "Chicago", "语法检查", "润色", "proofreading"],
        "semantic": ["main idea", "detail", "inference", "vocabulary in context", "complex sentence", "grammatical analysis", "paragraph structure", "logical relation", "paraphrase", "key word location", "scanning", "skimming", "note", "summary", "annotation", "topic sentence", "thesis", "evidence", "argumentation", "cohesion", "transition", "citation", "conclusion", "introduction", "reference", "APA", "MLA", "Chicago", "grammar check", "polishing", "proofreading"],
        "structure": ["文章-题目-解析结构", "段落-论点-论据结构", "引言-主体-结论结构"],
    },

    # ===== 小语种（1条） =====
    {
        "patterns": ["Japanese", "Korean", "German", "French", "Spanish", "Russian", "日语", "韩语", "德语", "法语", "西班牙语", "俄语", "小语种", "二外"],
        "support": ["五十音", "平假名", "片假名", "汉字", "日语语法", "敬语", "助词", "动词变形", "韩语字母", "发音", "语法", "格助词", "时制", "德语语法", "性数格", "变位", "法语语法", "阴阳性", "变位", "时态", "俄语语法", "格", "变位", "西班牙语速成", "动词变位", "时态"],
        "semantic": ["Japanese", "Korean", "German", "French", "Spanish", "Russian", "hiragana", "katakana", "kanji", "grammar", "keigo", "particle", "verb conjugation", "Korean alphabet", "pronunciation", "case particle", "tense", "gender", "number", "case", "conjugation", "tense", "aspect", "mood", "immersion", "comprehensive input"],
        "structure": ["语音-词汇-语法结构", "课文-练习-测试结构", "输入-模仿-输出结构"],
    },

    # ===== 中文文学（4条） =====
    {
        "patterns": ["Chinese classical literature", "古代文学", "古典文学", "诗经", "楚辞", "唐诗", "宋词", "元曲", "明清小说", "红楼梦", "西游记", "水浒传", "三国演义", "古文", "文言文"],
        "support": ["诗词", "格律", "韵脚", "对仗", "典故", "意象", "体裁", "赋", "比", "兴", "婉约派", "豪放派", "现实主义", "浪漫主义", "作者", "时代背景", "文学批评", "鉴赏", "注疏", "版本"],
        "semantic": ["poetry", "prosody", "rhyme", "antithesis", "allusion", "imagery", "genre", "fu", "bi", "xing", "elegant style", "bold style", "realism", "romanticism", "author", "historical context", "literary criticism", "appreciation", "annotation", "edition"],
        "structure": ["作者-时代-作品结构", "文本-注释-赏析结构", "体裁-风格-比较结构"],
    },
    {
        "patterns": ["modern Chinese literature", "contemporary literature", "现当代文学", "鲁迅", "茅盾", "巴金", "老舍", "沈从文", "张爱玲", "莫言", "余华", "外国文学", "比较文学", "世界文学"],
        "support": ["小说", "散文", "诗歌", "戏剧", "先锋文学", "寻根文学", "新写实", "朦胧诗", "伤痕文学", "反思文学", "现代主义", "后现代主义", "意识流", "魔幻现实主义", "叙事", "视角", "象征", "隐喻", "主题", "人物塑造"],
        "semantic": ["novel", "prose", "poetry", "drama", "avant-garde", "root-seeking", "new realism", "misty poetry", "scar literature", "reflection literature", "modernism", "postmodernism", "stream of consciousness", "magical realism", "narrative", "perspective", "symbol", "metaphor", "theme", "characterization"],
        "structure": ["作家-作品-流派结构", "情节-人物-主题结构", "文本-理论-批评结构"],
    },
    {
        "patterns": ["literary theory", "文艺学", "文学理论", "美学", "西方文论", "中国文论", "叙事学", "符号学", "接受美学", "解构主义", "女性主义", "后殖民主义"],
        "support": ["摹仿说", "表现说", "形式", "内容", "文本", "读者", "作者", "意图", "互文性", "叙事学", "热奈特", "原型", "集体无意识", "陌生化", "典型", "意境", "意象", "风骨", "神韵", "性灵"],
        "semantic": ["mimesis", "expression", "form", "content", "text", "reader", "author", "intention", "intertextuality", "narratology", "Genette", "archetype", "collective unconscious", "defamiliarization", "typicality", "artistic conception", "imagery", "vigor", "spirit", "innate sensibility"],
        "structure": ["概念-定义-例证结构", "理论-文本-应用结构", "比较-综合-创新结构"],
    },
    {
        "patterns": ["linguistics", "汉语言文学", "语言学", "现代汉语", "古代汉语", "语法", "语音", "语义", "语用", "方言", "社会语言学", "心理语言学", "计算语言学", "语料库"],
        "support": ["音素", "音位", "音节", "声母", "韵母", "声调", "语素", "词", "短语", "句子", "成分", "主语", "谓语", "宾语", "定语", "状语", "补语", "词类", "实词", "虚词", "句型", "修辞", "比喻", "拟人", "排比", "对偶", "方言", "普通话"],
        "semantic": ["phoneme", "phoneme", "syllable", "initial", "final", "tone", "morpheme", "word", "phrase", "sentence", "component", "subject", "predicate", "object", "attributive", "adverbial", "complement", "part of speech", "content word", "function word", "sentence pattern", "rhetoric", "metaphor", "personification", "parallelism", "antithesis", "dialect", "Mandarin"],
        "structure": ["语言单位-层级-规则结构", "例句-分析-归纳结构", "对比-演变-解释结构"],
    },

    # ===== 历史与哲学（4条） =====
    {
        "patterns": ["history", "Chinese history", "world history", "历史学", "中国历史", "世界史", "古代史", "近现代史", "考古", "史料", "年鉴学派", "全球史", "文化史", "思想史"],
        "support": ["朝代", "年号", "事件", "人物", "制度", "经济", "政治", "文化", "军事", "外交", "史料", "文献", "考古", "文物", "地层", "碳十四", "口述史", "记忆", "叙事", "解释", "因果", "比较", "长时段", "结构", "趋势"],
        "semantic": ["dynasty", "era name", "event", "figure", "institution", "economy", "politics", "culture", "military", "diplomacy", "historical source", "document", "archaeology", "relic", "stratum", "radiocarbon dating", "oral history", "memory", "narrative", "interpretation", "causality", "comparison", "longue duree", "structure", "trend"],
        "structure": ["时间-事件-影响结构", "史料-考证-结论结构", "比较-综合-解释结构"],
    },
    {
        "patterns": ["philosophy", "Western philosophy", "Chinese philosophy", "哲学", "西方哲学", "中国哲学", "伦理学", "逻辑学", "认识论", "形而上学", "存在主义", "分析哲学", "康德", "黑格尔", "尼采", "孔子", "老子", "庄子"],
        "support": ["本体论", "认识论", "伦理学", "美学", "逻辑", "辩证法", "形而上学", "存在", "意识", "理性", "经验", "先验", "超验", "自由", "必然", "善", "恶", "正义", "德性", "道", "仁", "义", "礼", "智", "信", "无为", "自然", "天人合一", "知行合一"],
        "semantic": ["ontology", "epistemology", "ethics", "aesthetics", "logic", "dialectic", "metaphysics", "existence", "consciousness", "reason", "experience", "a priori", "transcendental", "freedom", "necessity", "good", "evil", "justice", "virtue", "Tao", "benevolence", "righteousness", "propriety", "wisdom", "faith", "wu wei", "nature", "unity of heaven and man", "unity of knowledge and action"],
        "structure": ["问题-论证-结论结构", "概念-辨析-应用结构", "文本-解释-批判结构"],
    },
    {
        "patterns": ["art history", "music theory", "戏剧", "影视理论", "艺术史", "音乐理论", "戏剧理论", "电影理论", "美学", "艺术批评"],
        "support": ["艺术", "风格", "流派", "时期", "文艺复兴", "巴洛克", "古典主义", "浪漫主义", "现实主义", "印象派", "现代主义", "后现代主义", "音乐", "和声", "对位", "曲式", "配器", "戏剧", "悲剧", "喜剧", "冲突", "角色", "情节", "电影", "镜头", "剪辑", "蒙太奇", "长镜头", "叙事", "类型", "作者论", "意识形态批评"],
        "semantic": ["art", "style", "school", "period", "Renaissance", "Baroque", "Classicism", "Romanticism", "Realism", "Impressionism", "Modernism", "Postmodernism", "music", "harmony", "counterpoint", "form", "orchestration", "drama", "tragedy", "comedy", "conflict", "character", "plot", "film", "shot", "editing", "montage", "long take", "narrative", "genre", "auteur theory", "ideological criticism"],
        "structure": ["作品-风格-时代结构", "技法-分析-评价结构", "理论-文本-批评结构"],
    },
    {
        "patterns": ["aesthetics", "美学", "艺术哲学", "审美", "美的本质", "审美经验", "审美判断", "崇高", "优美", "悲剧性", "喜剧性"],
        "support": ["美", "审美", "美感", "审美经验", "审美判断", "审美态度", "无利害", "距离", "移情", "直觉", "表现", "形式", "符号", "意象", "典型", "意境", "崇高", "优美", "悲剧", "喜剧", "荒诞", "丑", "自然美", "艺术美", "社会美", "技术美", "设计美", "美育"],
        "semantic": ["beauty", "aesthetic", "aesthetic feeling", "aesthetic experience", "aesthetic judgment", "aesthetic attitude", "disinterestedness", "distance", "empathy", "intuition", "expression", "form", "symbol", "imagery", "typicality", "artistic conception", "sublime", "grace", "tragedy", "comedy", "absurd", "ugly", "natural beauty", "artistic beauty", "social beauty", "technical beauty", "design beauty", "aesthetic education"],
        "structure": ["概念-历史-理论结构", "经验-分析-判断结构", "比较-综合-创新结构"],
    },

    # ===== 经济与商科（8条） =====
    {
        "patterns": ["microeconomics", "宏观经济学", "microeconomics", "macroeconomics", "经济学", "微观经济学", "宏观经济学", "博弈论", "信息经济学", "行为经济学", "劳动经济学", "发展经济学"],
        "support": ["供给", "需求", "均衡", "价格", "弹性", "效用", "边际", "成本", "收益", "利润", "市场", "垄断", "寡头", "竞争", "GDP", "CPI", "通货膨胀", "失业", "利率", "汇率", "财政政策", "货币政策", "IS-LM", "AD-AS", "索洛模型", "回归", "OLS", "内生性", "工具变量", "面板数据", "时间序列"],
        "semantic": ["supply", "demand", "equilibrium", "price", "elasticity", "utility", "marginal", "cost", "revenue", "profit", "market", "monopoly", "oligopoly", "competition", "GDP", "CPI", "inflation", "unemployment", "interest rate", "exchange rate", "fiscal policy", "monetary policy", "IS-LM", "AD-AS", "Solow model", "regression", "OLS", "endogeneity", "instrumental variable", "panel data", "time series"],
        "structure": ["模型-假设-推导结构", "数据-估计-检验结构", "理论-政策-效果结构"],
    },
    {
        "patterns": ["econometrics", "计量经济学", "面板数据", "时间序列", "工具变量", "DID", "RDD", "断点回归"],
        "support": ["回归", "OLS", "最小二乘", "假设检验", "置信区间", "显著性", "p值", "t检验", "F检验", "异方差", "自相关", "多重共线性", "内生性", "工具变量", "2SLS", "GMM", "面板数据", "固定效应", "随机效应", "DID", "双重差分", "RDD", "断点回归", "时间序列", "ARMA", "VAR", "协整", "Granger因果", "预测", "机器学习"],
        "semantic": ["regression", "OLS", "least squares", "hypothesis testing", "confidence interval", "significance", "p-value", "t-test", "F-test", "heteroskedasticity", "autocorrelation", "multicollinearity", "endogeneity", "instrumental variable", "2SLS", "GMM", "panel data", "fixed effect", "random effect", "DID", "difference-in-differences", "RDD", "regression discontinuity", "time series", "ARMA", "VAR", "cointegration", "Granger causality", "forecasting", "machine learning"],
        "structure": ["模型-估计-推断结构", "数据-检验-修正结构", "实证-结果-讨论结构"],
    },
    {
        "patterns": ["finance", "investment", "corporate finance", "金融学", "公司金融", "投资学", "货币银行学", "国际金融", "衍生品", "期权", "期货", "风险管理", "估值", "DCF", "WACC"],
        "support": ["货币", "银行", "信用", "利率", "汇率", "金融市场", "资本市场", "股票", "债券", "基金", "衍生品", "期权", "期货", "互换", "远期", "风险管理", "VaR", "投资组合", "CAPM", "APT", "有效市场", "行为金融", "公司估值", "DCF", "WACC", "FCFF", "FCFE", "并购", "IPO"],
        "semantic": ["money", "bank", "credit", "interest rate", "exchange rate", "financial market", "capital market", "stock", "bond", "fund", "derivative", "option", "future", "swap", "forward", "risk management", "VaR", "portfolio", "CAPM", "APT", "EMH", "behavioral finance", "valuation", "DCF", "WACC", "FCFF", "FCFE", "M&A", "IPO"],
        "structure": ["现金流-折现-估值结构", "资产-风险-收益结构", "市场-工具-策略结构"],
    },
    {
        "patterns": ["accounting", "financial management", "会计学", "财务管理", "成本会计", "管理会计", "审计", "CPA会计", "财务报表", "资产负债表", "利润表", "现金流量表"],
        "support": ["资产", "负债", "所有者权益", "收入", "费用", "利润", "科目", "分录", "凭证", "账簿", "总账", "明细账", "报表", "资产负债表", "利润表", "现金流量表", "比率分析", "杜邦分析", "预算", "成本控制", "存货", "折旧", "摊销", "减值", "审计", "内控", "风险评估"],
        "semantic": ["asset", "liability", "equity", "revenue", "expense", "profit", "account", "journal entry", "voucher", "ledger", "general ledger", "subsidiary ledger", "financial statement", "balance sheet", "income statement", "cash flow statement", "ratio analysis", "DuPont analysis", "budget", "cost control", "inventory", "depreciation", "amortization", "impairment", "audit", "internal control", "risk assessment"],
        "structure": ["交易-分录-报表结构", "数据-分析-决策结构", "审计-证据-结论结构"],
    },
    {
        "patterns": ["management", "organizational behavior", "HR", "管理学", "组织行为学", "人力资源管理", "战略管理", "运营管理", "供应链管理", "领导力", "团队管理", "OKR", "KPI", "绩效管理"],
        "support": ["计划", "组织", "领导", "控制", "战略", "目标", "使命", "愿景", "价值观", "SWOT", "PEST", "五力模型", "价值链", "核心竞争力", "组织", "结构", "文化", "变革", "激励", "马斯洛", "赫茨伯格", "期望理论", "公平理论", "领导", "风格", "团队", "沟通", "冲突", "决策", "招聘", "培训", "绩效", "薪酬", "OKR", "KPI", "360度", "供应链", "物流", "库存", "JIT", "精益", "六西格玛"],
        "semantic": ["planning", "organizing", "leading", "controlling", "strategy", "goal", "mission", "vision", "value", "SWOT", "PEST", "Porter's five forces", "value chain", "core competency", "organization", "structure", "culture", "change", "motivation", "Maslow", "Herzberg", "expectancy theory", "equity theory", "leadership", "style", "team", "communication", "conflict", "decision-making", "recruitment", "training", "performance", "compensation", "OKR", "KPI", "360-degree", "supply chain", "logistics", "inventory", "JIT", "lean", "Six Sigma"],
        "structure": ["分析-战略-执行结构", "组织-行为-绩效结构", "流程-优化-控制结构"],
    },
    {
        "patterns": ["marketing", "market research", "市场营销", "市场调研", "消费者行为", "品牌管理", "广告学", "数字营销", "SEO", "SEM", "社交媒体营销", "内容营销"],
        "support": ["市场", "细分", "目标", "定位", "STP", "4P", "产品", "价格", "渠道", "促销", "品牌", "定位", "认知", "态度", "忠诚度", "消费者", "需求", "动机", "感知", "学习", "决策", "调研", "问卷", "焦点小组", "深度访谈", "数据", "洞察", "广告", "创意", "媒介", "效果", "ROI", "转化率", "漏斗", "AARRR", "SEO", "SEM", "KOL", "KOC"],
        "semantic": ["market", "segmentation", "targeting", "positioning", "STP", "4P", "product", "price", "place", "promotion", "brand", "perception", "attitude", "loyalty", "consumer", "need", "motivation", "perception", "learning", "decision", "research", "questionnaire", "focus group", "in-depth interview", "data", "insight", "advertising", "creative", "media", "effectiveness", "ROI", "conversion rate", "funnel", "AARRR", "SEO", "SEM", "KOL", "KOC"],
        "structure": ["STP-4P-执行结构", "数据-洞察-策略结构", "投放-监测-优化结构"],
    },

    # ===== 法学类（4条） =====
    {
        "patterns": ["law", "civil law", "criminal law", "constitutional law", "法学", "民法", "刑法", "宪法", "行政法", "商法", "经济法", "国际法", "诉讼法", "知识产权法", "环境法", "劳动法"],
        "support": ["法律", "法规", "条例", "司法解释", "案例", "判例", "法条", "罪名", "构成要件", "主体", "客体", "主观方面", "客观方面", "因果关系", "过错", "责任", "权利", "义务", "合同", "侵权", "物权", "债权", "继承", "婚姻家庭", "公司", "证券", "票据", "保险", "海商", "专利", "商标", "著作权", "诉讼", "仲裁", "调解", "证据", "举证", "质证", "辩论", "判决", "裁定"],
        "semantic": ["law", "regulation", "rule", "judicial interpretation", "case", "precedent", "article", "crime", "element", "subject", "object", "subjective aspect", "objective aspect", "causality", "fault", "liability", "right", "obligation", "contract", "tort", "property right", "creditor's right", "inheritance", "marriage", "family", "company", "securities", "bill", "insurance", "maritime", "patent", "trademark", "copyright", "litigation", "arbitration", "mediation", "evidence", "burden of proof", "cross-examination", "debate", "judgment", "ruling"],
        "structure": ["法条-解释-适用结构", "要件-事实-判断结构", "证据-论证-结论结构"],
    },
    {
        "patterns": ["judicial examination", "bar exam", "法考", "司法考试", "律师资格考试", "法律职业资格考试", "客观题", "主观题", "案例分析", "法条分析"],
        "support": ["法条", "罪名", "构成要件", "案例分析", "法律关系", "请求权基础", "抗辩", "举证责任", "证明标准", "诉讼时效", "除斥期间", "管辖", "当事人", "证据", "判决理由", "法律适用", "司法解释", "指导案例", "真题", "模拟题", "速记", "口诀"],
        "semantic": ["legal provision", "crime", "element", "case analysis", "legal relationship", "claim basis", "defense", "burden of proof", "standard of proof", "limitation", "period of exclusion", "jurisdiction", "party", "evidence", "reasoning", "application of law", "judicial interpretation", "guiding case", "past paper", "mock test", "quick memory", "mnemonic"],
        "structure": ["案情-法律-结论结构", "法条-要件-匹配结构", "真题-解析-总结结构"],
    },
    {
        "patterns": ["international law", "commercial law", "economic law", "国际法", "国际公法", "国际私法", "国际经济法", "商法", "公司法", "证券法", "破产法", "海商法"],
        "support": ["条约", "公约", "协定", "国际习惯", "一般法律原则", "司法判例", "公法学家学说", "国家", "国际组织", "个人", "领土", "海洋法", "空气空间", "外层空间", "外交", "领事", "条约法", "国家责任", "国际争端", "国际法院", "WTO", "国际贸易", "投资", "仲裁", "冲突规范", "准据法", "公司", "股东", "董事", "监事会", "证券", "股票", "债券", "信息披露", "破产", "重整", "清算", "票据", "提单", "信用证", "保险", "共同海损"],
        "semantic": ["treaty", "convention", "agreement", "international custom", "general principles", "judicial decisions", "publicists", "state", "international organization", "individual", "territory", "law of the sea", "airspace", "outer space", "diplomacy", "consul", "treaty law", "state responsibility", "international dispute", "ICJ", "WTO", "international trade", "investment", "arbitration", "conflict rule", "applicable law", "company", "shareholder", "director", "board of supervisors", "securities", "stock", "bond", "disclosure", "bankruptcy", "reorganization", "liquidation", "bill", "B/L", "L/C", "insurance", "general average"],
        "structure": ["规范-主体-责任结构", "事实-法律-救济结构", "比较-冲突-适用结构"],
    },
    {
        "patterns": ["intellectual property", "IP", "知识产权", "专利法", "商标法", "著作权法", "反不正当竞争", "商业秘密"],
        "support": ["专利", "发明", "实用新型", "外观设计", "申请", "审查", "授权", "无效", "侵权", "赔偿", "商标", "注册", "异议", "撤销", "驰名", "混淆", "著作权", "作品", "作者", "权利", "许可", "转让", "合理使用", "法定许可", "网络传播", "技术措施", "反不正当竞争", "商业秘密", "竞业禁止", "地理标志", "植物新品种", "集成电路"],
        "semantic": ["patent", "invention", "utility model", "design", "application", "examination", "grant", "invalidation", "infringement", "damages", "trademark", "registration", "opposition", "cancellation", "well-known", "confusion", "copyright", "work", "author", "right", "license", "assignment", "fair use", "statutory license", "network transmission", "technological measure", "unfair competition", "trade secret", "non-compete", "geographical indication", "plant variety", "integrated circuit"],
        "structure": ["客体-权利-保护结构", "申请-审查-授权结构", "侵权-认定-救济结构"],
    },

    # ===== 社会科学（4条） =====
    {
        "patterns": ["psychology", "cognitive psychology", "社会心理学", "发展心理学", "临床心理学", "心理学", "认知", "情绪", "动机", "人格", "心理咨询", "实验心理学", "心理测量", "SPSS"],
        "support": ["感知", "注意", "记忆", "学习", "思维", "语言", "情绪", "动机", "人格", "智力", "态度", "从众", "服从", "群体", "依恋", "认知发展", "社会认知", "心理障碍", "疗法", "量表", "信度", "效度", "显著性", "p值", "SPSS"],
        "semantic": ["perception", "attention", "memory", "learning", "thinking", "language", "emotion", "motivation", "personality", "intelligence", "attitude", "conformity", "obedience", "group", "attachment", "cognitive development", "social cognition", "mental disorder", "therapy", "scale", "reliability", "validity", "significance", "p-value", "SPSS"],
        "structure": ["理论-实验-结论结构", "变量-测量-统计结构", "案例-分析-干预结构"],
    },
    {
        "patterns": ["sociology", "anthropology", "社会学", "人类学", "社会调查", "田野调查", "定量研究", "定性研究", "社会分层", "社会化", "文化", "仪式", "民族志"],
        "support": ["社会", "群体", "组织", "制度", "分层", "阶级", "流动", "社会化", "角色", "规范", "偏差", "犯罪", "家庭", "教育", "宗教", "文化", "仪式", "象征", "符号", "民族志", "田野", "访谈", "问卷", "参与观察"],
        "semantic": ["society", "group", "organization", "institution", "stratification", "class", "mobility", "socialization", "role", "norm", "deviance", "crime", "family", "education", "religion", "culture", "ritual", "symbol", "sign", "ethnography", "fieldwork", "interview", "questionnaire", "participant observation"],
        "structure": ["理论-假设-验证结构", "调查-数据-分析结构", "观察-描述-解释结构"],
    },
    {
        "patterns": ["journalism", "communication", "新闻传播学", "传播学", "新闻学", "媒介", "舆论", "受众", "效果研究", "内容分析", "框架理论", "议程设置", "把关人", "新媒体"],
        "support": ["新闻", "报道", "采访", "编辑", "评论", "舆论", "宣传", "公关", "广告", "媒介", "受众", "效果", "框架", "议程设置", "把关", "沉默的螺旋", "使用与满足", "编码", "解码", "内容分析", "文本分析", "话语分析", "质化", "量化", "焦点小组"],
        "semantic": ["news", "report", "interview", "edit", "commentary", "public opinion", "propaganda", "public relations", "advertising", "media", "audience", "effect", "framing", "agenda-setting", "gatekeeping", "spiral of silence", "uses and gratifications", "encoding", "decoding", "content analysis", "textual analysis", "discourse analysis", "qualitative", "quantitative", "focus group"],
        "structure": ["5W1H结构", "媒介-信息-受众结构", "理论-假设-验证结构"],
    },
    {
        "patterns": ["political science", "international relations", "政治学", "国际关系", "公共管理", "行政学", "公共政策", "比较政治", "政治哲学", "马克思主义", "自由主义", "保守主义"],
        "support": ["国家", "政府", "权力", "权威", "合法性", "民主", "专制", "宪政", "联邦", "集权", "分权", "选举", "政党", "利益集团", "公共政策", "行政", "官僚", "治理", "国际体系", "主权", "均势", "博弈", "合作", "冲突", "战争", "和平", "外交"],
        "semantic": ["state", "government", "power", "authority", "legitimacy", "democracy", "autocracy", "constitutionalism", "federalism", "centralization", "decentralization", "election", "political party", "interest group", "public policy", "administration", "bureaucracy", "governance", "international system", "sovereignty", "balance of power", "game", "cooperation", "conflict", "war", "peace", "diplomacy"],
        "structure": ["概念-理论-案例结构", "制度-行为-结果结构", "比较-归纳-解释结构"],
    },

    # ===== 视觉设计（4条） =====
    {
        "patterns": ["UI design", "UX design", "UI/UX", "interface design", "交互设计", "用户研究", "可用性测试", "原型设计", "Figma", "Sketch", "Axure", "Adobe XD", "设计系统", "Design System"],
        "support": ["用户", "需求", "场景", "任务", "流程", "信息架构", "导航", "布局", "网格", "组件", "按钮", "输入框", "表单", "列表", "卡片", "标签", "弹窗", "反馈", "动效", "转场", "色彩", "字体", "图标", "插画", "图片", "间距", "对齐", "对比", "重复", "亲密性", "可用性", "易用性", "可访问性", "A/B测试", "热力图", "眼动", "访谈", "问卷", " persona", "用户旅程", "故事板", "线框图", "高保真", "低保真"],
        "semantic": ["user", "need", "scenario", "task", "flow", "information architecture", "navigation", "layout", "grid", "component", "button", "input", "form", "list", "card", "tag", "modal", "feedback", "animation", "transition", "color", "typography", "icon", "illustration", "image", "spacing", "alignment", "contrast", "repetition", "proximity", "usability", "ease of use", "accessibility", "A/B test", "heatmap", "eye tracking", "interview", "questionnaire", "persona", "user journey", "storyboard", "wireframe", "high-fidelity", "low-fidelity"],
        "structure": ["需求-原型-测试结构", "信息架构-流程-界面结构", "组件-状态-交互结构"],
    },
    {
        "patterns": ["graphic design", "visual design", "平面设计", "视觉设计", "海报设计", "Logo设计", "品牌设计", "包装设计", "书籍装帧", "排版设计", "字体设计", "色彩设计", "Illustrator", "InDesign"],
        "support": ["构图", "布局", "对齐", "对比", "重复", "亲密性", "留白", "网格", "比例", "黄金分割", "色彩", "色相", "明度", "饱和度", "配色", "色环", "互补色", "类似色", "字体", "字号", "字重", "行距", "字间距", "段落", "标题", "正文", "图片", "图形", "图标", "插画", "摄影", "裁剪", "蒙版", "图层", "混合模式", "滤镜", "特效", "矢量", "位图", "分辨率", "DPI", "出血", "裁切线"],
        "semantic": ["composition", "layout", "alignment", "contrast", "repetition", "proximity", "white space", "grid", "proportion", "golden ratio", "color", "hue", "brightness", "saturation", "color matching", "color wheel", "complementary", "analogous", "font", "font size", "font weight", "line spacing", "letter spacing", "paragraph", "heading", "body text", "image", "graphics", "icon", "illustration", "photography", "crop", "mask", "layer", "blend mode", "filter", "effect", "vector", "raster", "resolution", "DPI", "bleed", "crop mark"],
        "structure": ["主题-概念-视觉结构", "元素-排版-色彩结构", "草稿-修改-定稿结构"],
    },
    {
        "patterns": ["brand design", "packaging design", "品牌设计", "包装设计", "VI设计", "CIS", "品牌策略", "品牌识别"],
        "support": ["品牌", "定位", "价值", "个性", "故事", "命名", "口号", "Logo", "标志", "VI", "视觉识别", "色彩系统", "字体系统", "图形系统", "应用系统", "名片", "信纸", "手册", "网站", "包装", "结构", "材料", "工艺", "印刷", "标签", "瓶型", "盒型", "袋型", "系列化", "延展", "规范", "手册", "指南"],
        "semantic": ["brand", "positioning", "value", "personality", "story", "naming", "slogan", "Logo", "mark", "VI", "visual identity", "color system", "typography system", "graphic system", "application system", "business card", "letterhead", "brochure", "website", "packaging", "structure", "material", "process", "printing", "label", "bottle", "box", "bag", "serialization", "extension", "guideline", "manual"],
        "structure": ["策略-定位-识别结构", "概念-设计-规范结构", "应用-延展-管理结构"],
    },
    {
        "patterns": ["photography", "photo editing", "摄影", "修图", "拍照", "商业摄影", "人像摄影", "风光摄影", "Lightroom", "Photoshop"],
        "support": ["相机", "镜头", "光圈", "快门", "感光度", "焦距", "景深", "曝光", "白平衡", "对焦", "构图", "三分法", "引导线", "框架", "对称", "对比", "光影", "色彩", "色调", "饱和度", "RAW", "后期", "Lightroom", "Photoshop", "调色", "修图", "磨皮", "液化", "裁剪", "旋转", "透视", "HDR", "全景", "延时", "慢门"],
        "semantic": ["camera", "lens", "aperture", "shutter", "ISO", "focal length", "depth of field", "exposure", "white balance", "focus", "composition", "rule of thirds", "leading line", "frame", "symmetry", "contrast", "light", "color", "tone", "saturation", "RAW", "post-processing", "Lightroom", "Photoshop", "color grading", "retouching", "skin smoothing", "liquify", "crop", "rotate", "perspective", "HDR", "panorama", "time-lapse", "long exposure"],
        "structure": ["主题-构图-曝光结构", "拍摄-选片-后期结构", "色彩-质感-输出结构"],
    },

    # ===== 三维与工业（4条） =====
    {
        "patterns": ["industrial design", "product design", "工业设计", "产品设计", "家具设计", "家电设计", "交通工具设计", "CMF", "人机工程学", "犀牛", "Rhino", "KeyShot", "C4D"],
        "support": ["草图", "手绘", "建模", "渲染", "CMF", "颜色", "材料", "工艺", "表面处理", "人机", "人体尺寸", "握持", "操作", "交互", "结构", "装配", "制造", "3D打印", "CNC", "注塑", "钣金", "模具", "成本", "量产", "包装", "运输", "环保", "可持续", "生命周期"],
        "semantic": ["sketch", "hand drawing", "modeling", "rendering", "CMF", "color", "material", "finish", "surface treatment", "ergonomics", "anthropometry", "grip", "operation", "interaction", "structure", "assembly", "manufacturing", "3D printing", "CNC", "injection molding", "sheet metal", "mold", "cost", "mass production", "packaging", "transportation", "environmental", "sustainable", "life cycle"],
        "structure": ["调研-概念-方案结构", "草图-建模-渲染结构", "结构-材料-工艺结构"],
    },
    {
        "patterns": ["3D modeling", "3D rendering", "三维建模", "三维渲染", "Blender", "Maya", "C4D", "3ds Max", "ZBrush", "Substance", "V-Ray", "Arnold", "Octane"],
        "support": ["建模", "多边形", "NURBS", "细分", "雕刻", "拓扑", "UV", "展开", "贴图", "材质", "PBR", "纹理", "烘焙", "灯光", "相机", "渲染", "全局光照", "光线追踪", "焦散", "环境光", "HDRI", "后期", "合成", "动画", "绑定", "骨骼", "权重", "关键帧", "曲线", "粒子", "流体", "布料", "刚体", "软体"],
        "semantic": ["modeling", "polygon", "NURBS", "subdivision", "sculpting", "topology", "UV", "unwrapping", "texture", "material", "PBR", "texture", "baking", "lighting", "camera", "rendering", "global illumination", "ray tracing", "caustic", "ambient light", "HDRI", "post-processing", "compositing", "animation", "rigging", "skeleton", "weight", "keyframe", "curve", "particle", "fluid", "cloth", "rigid body", "soft body"],
        "structure": ["概念-草图-模型结构", "建模-材质-渲染结构", "绑定-动画-输出结构"],
    },
    {
        "patterns": ["animation", "game art", "动画", "游戏美术", "原画", "概念设计", "角色设计", "场景设计", "3D建模", "贴图", "绑定", "动画", "特效", "VFX", "Unity", "Unreal", "Blender", "Maya", "ZBrush", "Substance"],
        "support": ["角色", "场景", "道具", "世界观", "设定", "草图", "线稿", "上色", "光影", "透视", "构图", "三视图", "比例", "解剖", "动态", "表情", "氛围", "风格", "3D模型", "拓扑", "UV", "贴图", "材质", "PBR", "着色器", "骨骼", "绑定", "权重", "动画", "关键帧", "曲线", "物理", "粒子", "特效", "VFX", "合成", "渲染", "后期", "剪辑", "音效"],
        "semantic": ["character", "scene", "prop", "worldview", "setting", "sketch", "line art", "coloring", "lighting", "perspective", "composition", "orthographic", "proportion", "anatomy", "pose", "expression", "atmosphere", "style", "3D model", "topology", "UV", "texture", "material", "PBR", "shader", "skeleton", "rigging", "weight", "animation", "keyframe", "curve", "physics", "particle", "VFX", "compositing", "rendering", "post-production", "editing", "sound effect"],
        "structure": ["概念-草图-定稿结构", "模型-贴图-渲染结构", "动画-特效-合成结构"],
    },
    {
        "patterns": ["architectural visualization", "建筑可视化", "建筑表现", "建筑动画", "Lumion", "Enscape", "Twinmotion", "D5渲染器"],
        "support": ["建筑", "室内", "景观", "规划", "模型", "材质", "灯光", "相机", "角度", "构图", "渲染", "实时渲染", "光线追踪", "后期", "PS", "调色", "配景", "人物", "植物", "车辆", "天空", "环境", "动画", "漫游", "飞行动画", "生长动画", "VR", "AR", "全景", "效果图", "平面图", "立面图", "剖面图", "分析图", "排版", "展板"],
        "semantic": ["architecture", "interior", "landscape", "planning", "model", "material", "lighting", "camera", "angle", "composition", "rendering", "real-time rendering", "ray tracing", "post-processing", "PS", "color grading", "entourage", "people", "vegetation", "vehicle", "sky", "environment", "animation", "walkthrough", "fly-through", "growth animation", "VR", "AR", "panorama", "rendering", "plan", "elevation", "section", "diagram", "layout", "panel"],
        "structure": ["模型-场景-渲染结构", "镜头-剪辑-后期结构", "图纸-分析-排版结构"],
    },

    # ===== 音视频（4条） =====
    {
        "patterns": ["video editing", "video production", "视频剪辑", "视频制作", "后期制作", "Premiere", "Final Cut", "DaVinci", "剪映", "AE"],
        "support": ["剪辑", "粗剪", "精剪", "转场", "特效", "调色", "校色", "LUT", "字幕", "配音", "配乐", "音效", "混音", "合成", "绿幕", "抠像", "跟踪", "稳定", "变速", "倒放", "分屏", "画中画", "多机位", "时间线", "轨道", "素材", "代理", "导出", "编码", "压缩", "格式", "分辨率", "帧率", "码率", "Premiere", "Final Cut", "DaVinci", "After Effects", "剪映"],
        "semantic": ["editing", "rough cut", "fine cut", "transition", "effect", "color grading", "color correction", "LUT", "subtitle", "dubbing", "soundtrack", "sound effect", "mixing", "compositing", "green screen", "keying", "tracking", "stabilization", "speed change", "reverse", "split screen", "picture in picture", "multi-camera", "timeline", "track", "footage", "proxy", "export", "encoding", "compression", "format", "resolution", "frame rate", "bitrate", "Premiere", "Final Cut", "DaVinci", "After Effects"],
        "structure": ["素材-剪辑-调色结构", "画面-声音-节奏结构", "特效-合成-输出结构"],
    },
    {
        "patterns": ["audio production", "sound design", "音频制作", "混音", "母带", "音效设计", "Pro Tools", "Logic Pro", "Ableton", "FL Studio"],
        "support": ["录音", "话筒", "声卡", "调音台", "音频接口", "监听", "耳机", "音箱", "声学", "吸音", "扩散", "隔音", "编辑", "剪辑", "降噪", "修复", "均衡", "EQ", "压缩", "限制", "混响", "延迟", "合唱", "镶边", "失真", "饱和", "声像", "声场", "混音", "平衡", "频率", "动态", "母带", "响度", " dB", "采样率", "位深", "MIDI", "虚拟乐器", "音源", "编曲", "配器", "和声", "对位"],
        "semantic": ["recording", "microphone", "sound card", "mixer", "audio interface", "monitoring", "headphone", "speaker", "acoustics", "absorption", "diffusion", "isolation", "editing", "cutting", "noise reduction", "restoration", "equalization", "EQ", "compression", "limiting", "reverb", "delay", "chorus", "flanger", "distortion", "saturation", "panning", "soundstage", "mixing", "balance", "frequency", "dynamics", "mastering", "loudness", "dB", "sample rate", "bit depth", "MIDI", "virtual instrument", "sound source", "arrangement", "orchestration", "harmony", "counterpoint"],
        "structure": ["录音-编辑-混音结构", "编曲-配器-制作结构", "效果-平衡-母带结构"],
    },
    {
        "patterns": ["music composition", "songwriting", "音乐创作", "作曲", "编曲", "写歌", "歌词", "旋律", "和声", "配器"],
        "support": ["作曲", "旋律", "动机", "主题", "变奏", "发展", "再现", "曲式", "奏鸣曲", "回旋曲", "变奏曲", "赋格", "和弦", "和声", "调性", "调式", "转调", "离调", "节奏", "节拍", "速度", "力度", "音色", "织体", "配器", "编曲", "MIDI", "打谱", "Sibelius", "Finale", "Cubase", "Logic", "写歌", "歌词", "韵脚", "结构", "主歌", "副歌", "桥段", "尾奏"],
        "semantic": ["composition", "melody", "motive", "theme", "variation", "development", "recapitulation", "form", "sonata", "rondo", "variation", "fugue", "chord", "harmony", "tonality", "mode", "modulation", "tempo", "meter", "rhythm", "dynamics", "timbre", "texture", "orchestration", "arrangement", "MIDI", "notation", "Sibelius", "Finale", "Cubase", "Logic", "songwriting", "lyrics", "rhyme", "structure", "verse", "chorus", "bridge", "outro"],
        "structure": ["动机-发展-曲式结构", "和声-旋律-织体结构", "编曲-录制-混音结构"],
    },
    {
        "patterns": ["live streaming", "主播", "直播", "带货", "直播间", "OBS", "推流", "弹幕", "打赏"],
        "support": ["直播", "主播", "摄像头", "麦克风", "灯光", "背景", "绿幕", "OBS", "推流", "码率", "帧率", "分辨率", "平台", "抖音", "快手", "B站", "淘宝", "京东", "带货", "选品", "脚本", "话术", "互动", "弹幕", "评论", "点赞", "关注", "粉丝", "打赏", "礼物", "连麦", "PK", "切片", "回放", "数据", "流量", "转化率", "GMV"],
        "semantic": ["live streaming", "streamer", "camera", "microphone", "lighting", "background", "green screen", "OBS", "push stream", "bitrate", "frame rate", "resolution", "platform", "Douyin", "Kuaishou", "Bilibili", "Taobao", "JD", "live commerce", "product selection", "script", "pitch", "interaction", "bullet comment", "comment", "like", "follow", "fan", "tip", "gift", "co-host", "PK", "clip", "replay", "data", "traffic", "conversion rate", "GMV"],
        "structure": ["设备-场景-画面结构", "内容-互动-转化结构", "数据-复盘-优化结构"],
    },

    # ===== 表演艺术（5条） =====
    {
        "patterns": ["acting", "theatre", "表演", "戏剧", "话剧", "舞台剧", "独角戏", "即兴表演", "斯坦尼斯拉夫斯基", "方法派"],
        "support": ["表演", "演员", "角色", "台词", "肢体", "表情", "声音", "气息", "情绪", "记忆", "想象力", "注意力", "信念感", "适应", "交流", "行动", "目的", "障碍", "冲突", "节奏", "调度", "舞台", "灯光", "布景", "服装", "化妆", "道具", "导演", "剧本", "排练", "合成", "演出", "谢幕"],
        "semantic": ["acting", "actor", "role", "line", "body", "expression", "voice", "breath", "emotion", "memory", "imagination", "attention", "belief", "adaptation", "interaction", "action", "objective", "obstacle", "conflict", "rhythm", "blocking", "stage", "lighting", "set", "costume", "makeup", "prop", "director", "script", "rehearsal", "technical rehearsal", "performance", "curtain call"],
        "structure": ["剧本-分析-角色结构", "排练-调度-合成结构", "表演-反馈-调整结构"],
    },
    {
        "patterns": ["dance", "舞蹈", "古典舞", "民族舞", "现代舞", "街舞", "芭蕾", "爵士", "编舞"],
        "support": ["舞蹈", "动作", "姿态", "步伐", "转身", "跳跃", "旋转", "平衡", "柔韧", "力量", "节奏", "音乐", "节拍", "情感", "表达", "风格", "古典", "民间", "现代", "当代", "街舞", "Breaking", "Popping", "Locking", "Hip-hop", "Jazz", "Ballet", "编舞", "编排", "队形", "舞台", "灯光", "服装", "排练", "演出"],
        "semantic": ["dance", "movement", "posture", "step", "turn", "jump", "spin", "balance", "flexibility", "strength", "rhythm", "music", "beat", "emotion", "expression", "style", "classical", "folk", "modern", "contemporary", "street dance", "Breaking", "Popping", "Locking", "Hip-hop", "Jazz", "Ballet", "choreography", "arrangement", "formation", "stage", "lighting", "costume", "rehearsal", "performance"],
        "structure": ["基本功-技巧-组合结构", "音乐-动作-情感结构", "编排-排练-演出结构"],
    },
    {
        "patterns": ["hosting", "broadcasting", "播音主持", "主持", "播音", "配音", "朗诵", "演讲", "口才", "普通话", "播音腔"],
        "support": ["播音", "主持", "配音", "朗诵", "演讲", "口才", "普通话", "发音", "吐字", "归音", "气息", "共鸣", "声调", "语调", "节奏", "停顿", "重音", "语速", "情感", "对象感", "内在语", "情景再现", "即兴口语", "串词", "开场", "衔接", "互动", "控场", "救场", "总结", "结束", "镜头感", "上镜", "仪容", "仪表"],
        "semantic": ["broadcasting", "hosting", "dubbing", "recitation", "speech", "eloquence", "Mandarin", "pronunciation", "articulation", "final sound", "breath", "resonance", "tone", "intonation", "rhythm", "pause", "stress", "speech rate", "emotion", "sense of audience", "subtext", "scene reconstruction", "impromptu speaking", "transition", "opening", "interaction", "crowd control", "saving the show", "summary", "ending", "camera sense", "on-camera", "appearance"],
        "structure": ["语音-发声-表达结构", "稿件-理解-呈现结构", "开场-推进-收束结构"],
    },
    {
        "patterns": ["directing", "filmmaking", "导演", "编导", "影视导演", "戏剧导演", "节目编导", "分镜", "脚本"],
        "support": ["导演", "编剧", "剧本", "分镜", "故事板", "镜头", "景别", "角度", "运动", "剪辑", "节奏", "表演", "调度", "美术", "灯光", "录音", "音乐", "后期", "合成", "调色", "导演阐述", "排练", "实拍", "跟组", "审片", "修改", "定剪", "发行", "宣发", "电影节", "展映", "获奖", "编导", "策划", "选题", "采访", "撰稿", "剪辑", "包装", "播出"],
        "semantic": ["director", "screenwriter", "script", "storyboard", "shot", "frame size", "angle", "movement", "editing", "rhythm", "acting", "blocking", "art direction", "lighting", "sound recording", "music", "post-production", "compositing", "color grading", "director's statement", "rehearsal", "shooting", "on set", "review", "revision", "final cut", "distribution", "promotion", "film festival", "screening", "award", "producer-director", "planning", "topic selection", "interview", "writing", "editing", "packaging", "broadcast"],
        "structure": ["剧本-分镜-拍摄结构", "表演-调度-剪辑结构", "策划-执行-播出结构"],
    },
    {
        "patterns": ["stage management", "production", "舞台管理", "制片", "剧场管理", "演出制作", "活动执行", "策展"],
        "support": ["舞台", "剧场", "观众", "演员", "排练", "合成", "装台", "拆台", "灯光", "音响", "道具", "服装", "化妆", "特效", "安全", "预算", "合同", "宣传", "票务", "票房", "赞助", "制片", "立项", "预算", "融资", "筹备", "拍摄", "后期", "发行", "宣传", "活动", "策划", "执行", "场地", "搭建", "流程", "物料", "人员", "策展", "展览", "展品", "展陈", "开幕", "导览"],
        "semantic": ["stage", "theater", "audience", "actor", "rehearsal", "technical rehearsal", "load-in", "strike", "lighting", "sound", "prop", "costume", "makeup", "special effect", "safety", "budget", "contract", "promotion", "ticketing", "box office", "sponsorship", "production", "project approval", "financing", "preparation", "shooting", "post-production", "distribution", "publicity", "event", "planning", "execution", "venue", "construction", "process", "material", "staff", "curation", "exhibition", "exhibit", "display", "opening", "guided tour"],
        "structure": ["策划-预算-执行结构", "排练-合成-演出结构", "筹备-实施-评估结构"],
    },

    # ===== 写作与内容（4条） =====
    {
        "patterns": ["academic writing", "thesis writing", "论文写作", "学位论文", "毕业论文", "开题报告", "文献综述", "SCI写作", "学术英语"],
        "support": ["选题", "文献综述", "研究背景", "研究意义", "研究目标", "研究问题", "假设", "理论框架", "研究方法", "实验设计", "数据收集", "数据分析", "结果", "讨论", "结论", "创新点", "局限性", "未来研究", "参考文献", "引用", "格式", "APA", "MLA", "Chicago", "GB/T", "摘要", "关键词", "目录", "致谢", "附录", "查重", "降重", "盲审", "修改", "答辩", "PPT"],
        "semantic": ["thesis", "dissertation", "bachelor thesis", "master thesis", "PhD thesis", "proposal", "mid-term check", "pre-defense", "defense", "blind review", "plagiarism check", "CNKI", "Turnitin", "topic selection", "literature review", "research background", "significance", "objective", "research question", "hypothesis", "theoretical framework", "methodology", "experimental design", "data collection", "data analysis", "result", "discussion", "conclusion", "innovation", "limitation", "future work", "reference", "citation", "format", "APA", "MLA", "Chicago", "GB/T", "abstract", "keyword", "table of contents", "acknowledgment", "appendix", "paraphrase", "revision", "presentation", "PPT"],
        "structure": ["引言-方法-结果-讨论结构", "文献-框架-论证结构", "数据-图表-分析结构"],
    },
    {
        "patterns": ["creative writing", "novel writing", "fiction", "创意写作", "写小说", "网文", "短篇小说", "剧本", "诗歌创作", "散文写作"],
        "support": ["小说", "故事", "情节", "冲突", "悬念", "转折", "高潮", "结局", "人物", "性格", "动机", "成长", "关系", "背景", "世界观", "设定", "视角", "叙事", "描写", "对话", "节奏", "风格", "主题", "象征", "隐喻", "伏笔", "铺垫", "呼应", "网文", "签约", "连载", "更新", "读者", "评论", "收藏", "推荐", "榜单", "剧本", "场景", "镜头", "台词", "动作", "诗歌", "意象", "韵律", "节奏", "分行"],
        "semantic": ["novel", "story", "plot", "conflict", "suspense", "twist", "climax", "ending", "character", "personality", "motivation", "growth", "relationship", "setting", "worldbuilding", "point of view", "narrative", "description", "dialogue", "pacing", "style", "theme", "symbol", "metaphor", "foreshadowing", "setup", "callback", "web novel", "contract", "serialization", "update", "reader", "comment", "bookmark", "recommendation", "ranking", "screenplay", "scene", "shot", "line", "action", "poetry", "imagery", "rhyme", "meter", "line break"],
        "structure": ["构思-大纲-写作结构", "人物-情节-主题结构", "草稿-修改-定稿结构"],
    },
    {
        "patterns": ["self-media", "WeChat public account", "自媒体", "公众号", "小红书", "知乎", "今日头条", "百家号", "内容运营", "涨粉"],
        "support": ["自媒体", "公众号", "小红书", "知乎", "头条", "百家号", "B站", "抖音", "快手", "内容", "选题", "策划", "标题", "封面", "文案", "图文", "视频", "音频", "排版", "编辑", "发布", "推广", "引流", "涨粉", "互动", "评论", "转发", "点赞", "收藏", "数据", "阅读", "播放", "完播率", "转化率", "变现", "广告", "带货", "知识付费", "社群", "私域", "人设", "IP", "矩阵"],
        "semantic": ["self-media", "WeChat public account", "Xiaohongshu", "Zhihu", "Toutiao", "Baijiahao", "Bilibili", "Douyin", "Kuaishou", "content", "topic selection", "planning", "headline", "cover", "copywriting", "image-text", "video", "audio", "layout", "editing", "publishing", "promotion", "traffic", "follower growth", "interaction", "comment", "repost", "like", "bookmark", "data", "reading", "playback", "completion rate", "conversion rate", "monetization", "advertising", "live commerce", "knowledge payment", "community", "private domain", "persona", "IP", "matrix"],
        "structure": ["选题-创作-发布结构", "内容-互动-转化结构", "数据-复盘-优化结构"],
    },
    {
        "patterns": ["copywriting", "content strategy", "文案", "策划", "广告文案", "品牌文案", "营销文案", "公关文案", "活动策划"],
        "support": ["文案", "标题", "slogan", "口号", "故事", "洞察", "卖点", "痛点", "爽点", "泪点", "创意", "概念", "策略", "定位", "传播", "媒介", "渠道", "预算", "KPI", "ROI", "效果", "转化", "曝光", "点击", "活动", "策划", "主题", "流程", "环节", "物料", "场地", "人员", "执行", "控场", "应急", "总结", "复盘", "品牌", "公关", "舆情", "危机", "声明", "回应"],
        "semantic": ["copywriting", "headline", "slogan", "tagline", "story", "insight", "selling point", "pain point", "pleasure point", "tear point", "creative", "concept", "strategy", "positioning", "communication", "media", "channel", "budget", "KPI", "ROI", "effect", "conversion", "impression", "click", "event", "planning", "theme", "process", "segment", "material", "venue", "staff", "execution", "crowd control", "emergency", "summary", "review", "brand", "PR", "public opinion", "crisis", "statement", "response"],
        "structure": ["洞察-策略-创意结构", "概念-执行-效果结构", "策划-实施-复盘结构"],
    },

    # ===== 考试与考证（4条） =====
    {
        "patterns": ["postgraduate entrance exam", "考研", "研究生入学考试", "考研数学", "考研英语", "考研政治", "专业课", "复试", "调剂", "保研", "推免"],
        "support": ["大纲", "真题", "模拟题", "复习全书", "辅导讲义", "笔记", "错题", "考点", "重点", "难点", "公式", "定理", "概念", "定义", "证明", "计算", "英语单词", "阅读理解", "作文模板", "政治", "马原", "毛中特", "史纲", "思修", "时政", "专业课", "参考书", "课后题", "历年真题", "复试", "面试", "英语口语", "专业课面试", "调剂", "联系导师"],
        "semantic": ["postgraduate entrance exam", "master's", "PhD", "math", "English", "politics", "specialized course", "national exam", "self-designed", "re-examination", "adjustment", "recommendation", "exemption", "syllabus", "past paper", "mock test", "review book", "lecture notes", "notes", "mistake", "key point", "difficulty", "formula", "theorem", "concept", "definition", "proof", "calculation", "vocabulary", "reading comprehension", "essay template", "Marxism", "Mao Zedong Thought", "history", "ethics", "current affairs", "reference book", "exercise", "interview", "oral English", "supervisor"],
        "structure": ["章节-知识点-例题结构", "真题-解析-总结结构", "背诵-默写-检验结构"],
    },
    {
        "patterns": ["civil service exam", "公务员", "国考", "省考", "行测", "申论", "事业单位", "选调生", "三支一扶", "军转干"],
        "support": ["行测", "言语理解", "数量关系", "判断推理", "资料分析", "常识判断", "图形推理", "定义判断", "类比推理", "逻辑判断", "数字推理", "数学运算", "申论", "归纳概括", "综合分析", "提出对策", "贯彻执行", "大作文", "时政", "法律", "经济", "管理", "公文", "历史", "地理", "科技", "真题", "模拟", "押题", "面试", "结构化", "无领导", "试讲"],
        "semantic": ["civil service", "national exam", "provincial exam", "administrative aptitude test", "essay writing", "public institution", "selected graduate", "three supports and one assistance", "military transfer", "public basic knowledge", "occupational test", "comprehensive application", "verbal comprehension", "quantitative relation", "judgment reasoning", "data analysis", "general knowledge", "graphic reasoning", "definition judgment", "analogical reasoning", "logical judgment", "number sequence", "mathematical operation", "inductive summary", "comprehensive analysis", "countermeasure", "implementation", "major essay", "current affairs", "law", "economy", "management", "official document", "history", "geography", "science", "past paper", "mock", "prediction", "interview", "structured", "leaderless", "lecture"],
        "structure": ["题型-方法-练习结构", "材料-分析-作答结构", "真题-模拟-复盘结构"],
    },
    {
        "patterns": ["professional qualification", "职业资格考试", "CPA", "CFA", "ACCA", "FRM", "CMA", "税务师", "资产评估师", "造价工程师", "建造师", "监理工程师", "医师资格考试", "执业药师", "护士资格证", "教师资格证", "法律职业资格证"],
        "support": ["考试大纲", "教材", "辅导书", "网课", "真题", "模拟题", "章节练习", "考点", "重点", "难点", "公式", "法条", "准则", "标准", "规范", "流程", "操作", "病例", "处方", "教案", "教学设计", "会计分录", "财务报表", "审计报告", "估值模型", "风险管理", "投资组合", "税法", "经济法", "审计", "财管", "战略", "会计"],
        "semantic": ["qualification exam", "CPA", "CFA", "ACCA", "FRM", "CMA", "tax advisor", "asset appraiser", "cost engineer", "constructor", "supervision engineer", "physician", "pharmacist", "nurse", "teacher qualification", "bar exam", "syllabus", "textbook", "tutorial", "online course", "past paper", "mock", "chapter exercise", "key point", "difficulty", "formula", "legal provision", "standard", "guideline", "procedure", "operation", "case", "prescription", "lesson plan", "teaching design", "journal entry", "financial statement", "audit report", "valuation model", "risk management", "portfolio", "tax law", "economic law", "audit", "financial management", "strategy", "accounting"],
        "structure": ["章节-考点-练习结构", "案例-分析-结论结构", "真题-错题-总结结构"],
    },
    {
        "patterns": ["competition", "数学建模", "MCM", "ICM", "ACM", "程序设计竞赛", "电子设计竞赛", "挑战杯", "互联网+", "创新创业", "大创", "SRTP", "学科竞赛", "奥林匹克"],
        "support": ["建模", "模型", "假设", "符号", "变量", "方程", "算法", "求解", "验证", "灵敏度分析", "论文", "摘要", "问题重述", "模型建立", "模型求解", "模型评价", "编程", "代码", "调试", "测试", "电路", "硬件", "传感器", "单片机", "嵌入式", "方案", "设计", "制作", "调试", "演示", "PPT", "答辩", "商业计划书", "市场调研", "财务预测", "路演"],
        "semantic": ["mathematical modeling", "MCM", "ICM", "ACM", "programming contest", "electronic design contest", "Challenge Cup", "Internet+", "innovation", "entrepreneurship", "undergraduate research", "SRTP", "academic competition", "Olympiad", "model", "assumption", "symbol", "variable", "equation", "algorithm", "solution", "verification", "sensitivity analysis", "paper", "abstract", "problem restatement", "model establishment", "model solution", "model evaluation", "programming", "code", "debugging", "testing", "circuit", "hardware", "sensor", "microcontroller", "embedded", "proposal", "design", "production", "demonstration", "business plan", "market research", "financial forecast", "pitch"],
        "structure": ["问题-模型-求解结构", "方案-实现-测试结构", "策划-执行-展示结构"],
    },

    # ===== 办公技能（4条） =====
    {
        "patterns": ["Microsoft Office", "Word", "文档", "公文写作", "报告", "总结", "通知", "请示", "会议纪要"],
        "support": ["标题", "正文", "段落", "章节", "目录", "页眉", "页脚", "页码", "封面", "摘要", "关键词", "引言", "背景", "目的", "方法", "过程", "结果", "分析", "结论", "建议", "展望", "致谢", "参考文献", "附件", "表格", "图表", "图片", "流程图", "组织结构图", "修订", "批注", "比较", "合并", "模板", "样式", "大纲", "目录", "分页", "分节"],
        "semantic": ["document", "office", "report", "summary", "plan", "proposal", "scheme", "meeting minutes", "notice", "request", "approval", "title", "body", "paragraph", "chapter", "table of contents", "header", "footer", "page number", "cover", "abstract", "keyword", "introduction", "background", "purpose", "method", "process", "result", "analysis", "conclusion", "suggestion", "outlook", "acknowledgment", "reference", "attachment", "figure", "flowchart", "org chart", "revision", "comment", "compare", "combine", "template", "style", "outline", "section break"],
        "structure": ["标题-正文-结论结构", "数据-图表-说明结构", "封面-目录-内容结构"],
    },
    {
        "patterns": ["Excel", "spreadsheet", "表格", "数据分析", "数据可视化", "VBA", "Power Query", "数据透视表"],
        "support": ["工作簿", "工作表", "单元格", "行", "列", "区域", "公式", "函数", "SUM", "AVERAGE", "IF", "VLOOKUP", "INDEX", "MATCH", "数据透视表", "筛选", "排序", "条件格式", "图表", "柱状图", "折线图", "饼图", "散点图", "箱线图", "趋势线", "回归", "假设分析", "模拟运算", "规划求解", "宏", "VBA", "Power Query", "Power Pivot", "Power BI", "仪表盘", "自动化"],
        "semantic": ["workbook", "worksheet", "cell", "row", "column", "range", "formula", "function", "SUM", "AVERAGE", "IF", "VLOOKUP", "INDEX", "MATCH", "pivot table", "filter", "sort", "conditional formatting", "chart", "bar chart", "line chart", "pie chart", "scatter plot", "box plot", "trendline", "regression", "what-if analysis", "data table", "solver", "macro", "VBA", "Power Query", "Power Pivot", "Power BI", "dashboard", "automation"],
        "structure": ["数据-整理-分析结构", "公式-函数-结果结构", "图表-报告-决策结构"],
    },
    {
        "patterns": ["PowerPoint", "PPT", "演示文稿", "汇报", "路演", "答辩", "述职", "课件", "幻灯片"],
        "support": ["PPT", "幻灯片", "母版", "版式", "主题", "色彩", "字体", "背景", "图片", "图表", "图形", "SmartArt", "动画", "切换", "超链接", "音频", "视频", "备注", "演讲者视图", "排练计时", "汇报", "路演", "答辩", "述职", "课件", "教学", "逻辑", "结构", "开场", "主体", "结尾", "故事", "数据", "案例", "金句", "呼吁", "行动"],
        "semantic": ["PPT", "slide", "master slide", "layout", "theme", "color", "font", "background", "image", "chart", "shape", "SmartArt", "animation", "transition", "hyperlink", "audio", "video", "note", "presenter view", "rehearse timing", "presentation", "pitch", "defense", "performance review", "courseware", "teaching", "logic", "structure", "opening", "body", "ending", "story", "data", "case", "quote", "call to action"],
        "structure": ["逻辑-结构-视觉结构", "开场-主体-结尾结构", "数据-故事-行动结构"],
    },
    {
        "patterns": ["LaTeX", "Markdown", "Typora", "论文排版", "学术排版", "公式编辑", "文献引用", "交叉引用", "图表编号", "目录生成", "模板", "cls", "bst"],
        "support": ["LaTeX", "Markdown", "公式", "方程", "矩阵", "求和", "积分", "极限", "分式", "根号", "上标", "下标", "希腊字母", "字体", "字号", "行距", "页边距", "页眉", "页脚", "页码", "章节", "段落", "列表", "表格", "图片", "浮动体", "引用", "bib", "bibliography", "citation", "label", "ref", "交叉引用", "目录", "索引", "模板", "cls", "bst", "宏包", "package"],
        "semantic": ["LaTeX", "Markdown", "formula", "equation", "matrix", "summation", "integral", "limit", "fraction", "root", "superscript", "subscript", "Greek letter", "font", "font size", "line spacing", "margin", "header", "footer", "page number", "chapter", "paragraph", "list", "table", "figure", "float", "reference", "bib", "bibliography", "citation", "label", "ref", "cross-reference", "table of contents", "index", "template", "cls", "bst", "package"],
        "structure": ["结构-内容-排版结构", "公式-编号-引用结构", "模板-填充-编译结构"],
    },

    # ===== 健身与运动（4条） =====
    {
        "patterns": ["fitness", "strength training", "健身", "力量训练", "增肌", "减脂", "塑形", "健身房", "器械", "自由重量"],
        "support": ["健身", "训练", "力量", "增肌", "减脂", "塑形", "体能", "耐力", "爆发力", "柔韧性", "平衡", "协调", "热身", "拉伸", "放松", "恢复", "营养", "蛋白质", "碳水", "脂肪", "补剂", "肌酸", "蛋白粉", "BCAA", "健身房", "器械", "哑铃", "杠铃", " kettlebell", "深蹲", "硬拉", "卧推", "划船", "推举", "引体", "分化训练", "周期", "容量", "强度", "频率"],
        "semantic": ["fitness", "training", "strength", "muscle building", "fat loss", "shaping", "physical fitness", "endurance", "explosive power", "flexibility", "balance", "coordination", "warm-up", "stretching", "relaxation", "recovery", "nutrition", "protein", "carbohydrate", "fat", "supplement", "creatine", "protein powder", "BCAA", "gym", "equipment", "dumbbell", "barbell", "kettlebell", "squat", "deadlift", "bench press", "row", "overhead press", "pull-up", "split training", "periodization", "volume", "intensity", "frequency"],
        "structure": ["目标-计划-执行结构", "动作-组数-重量结构", "训练-饮食-恢复结构"],
    },
    {
        "patterns": ["running", "aerobic exercise", "跑步", "有氧运动", "马拉松", "慢跑", "游泳", "骑行", "划船", "椭圆机"],
        "support": ["跑步", "慢跑", "快跑", "间歇跑", "长跑", "马拉松", "半程马拉松", "配速", "步频", "步幅", "心率", "最大摄氧量", "乳酸阈值", "有氧", "无氧", "耐力", "游泳", "自由泳", "蛙泳", "仰泳", "蝶泳", "骑行", "自行车", "动感单车", "划船", "椭圆机", "跳绳", "HIIT", "Tabata", "热身", "拉伸", "装备", "跑鞋", "手表", "耳机"],
        "semantic": ["running", "jogging", "sprinting", "interval running", "long distance", "marathon", "half marathon", "pace", "cadence", "stride", "heart rate", "VO2 max", "lactate threshold", "aerobic", "anaerobic", "endurance", "swimming", "freestyle", "breaststroke", "backstroke", "butterfly", "cycling", "bicycle", "spinning", "rowing", "elliptical", "jump rope", "HIIT", "Tabata", "warm-up", "stretching", "gear", "running shoes", "watch", "headphone"],
        "structure": ["热身-训练-拉伸结构", "距离-配速-心率结构", "计划-执行-记录结构"],
    },
    {
        "patterns": ["ball sports", "team sports", "球类运动", "篮球", "足球", "排球", "羽毛球", "乒乓球", "网球", "棒球"],
        "support": ["篮球", "运球", "传球", "投篮", "防守", "战术", "配合", "足球", "传球", "射门", "防守", "越位", "角球", "任意球", "战术", "阵型", "排球", "发球", "垫球", "扣球", "拦网", "战术", "轮换", "羽毛球", "发球", "高远球", "扣杀", "吊球", "步法", "乒乓球", "发球", "接发球", "正手", "反手", "旋转", "网球", "发球", "底线", "截击", "高压", "棒球", "投球", "击球", "跑垒", "防守"],
        "semantic": ["basketball", "dribbling", "passing", "shooting", "defense", "tactics", "cooperation", "football", "soccer", "pass", "shoot", "defense", "offside", "corner kick", "free kick", "formation", "volleyball", "serve", "dig", "spike", "block", "rotation", "badminton", "clear", "smash", "drop shot", "footwork", "table tennis", "receive", "forehand", "backhand", "spin", "tennis", "baseline", "volley", "overhead", "baseball", "pitch", "hit", "base running", "fielding"],
        "structure": ["技术-战术-配合结构", "训练-比赛-复盘结构", "个人-团队-战略结构"],
    },
    {
        "patterns": ["yoga", "dance", "martial arts", "瑜伽", "普拉提", "舞蹈", "武术", "太极", "跆拳道", "拳击"],
        "support": ["瑜伽", "体式", "呼吸", "冥想", "放松", "拉伸", "核心", "平衡", "柔韧", "普拉提", "控制", "精准", "流畅", "呼吸", "舞蹈", "芭蕾", "爵士", "现代", "街舞", "民族", "拉丁", "动作", "节奏", "编排", "武术", "拳法", "腿法", "套路", "对练", "太极", "推手", "跆拳道", "品势", "竞技", "拳击", "步伐", "拳法", "防守", "闪躲", "组合拳"],
        "semantic": ["yoga", "asana", "breathing", "meditation", "relaxation", "stretching", "core", "balance", "flexibility", "Pilates", "control", "precision", "flow", "dance", "ballet", "jazz", "modern", "street dance", "folk dance", "Latin", "movement", "rhythm", "choreography", "martial arts", "fist", "kick", "form", "sparring", "Taichi", "push hand", "Taekwondo", "poomsae", "kyorugi", "boxing", "footwork", "punch", "defense", "dodge", "combination"],
        "structure": ["热身-练习-放松结构", "基础-进阶-提升结构", "动作-节奏-表达结构"],
    },

    # ===== 烹饪与生活（4条） =====
    {
        "patterns": ["cooking", "baking", "烹饪", "烘焙", "做菜", "中餐", "西餐", "日料", "甜点", "面包"],
        "support": ["烹饪", "食材", "配料", "调料", "刀工", "火候", "油温", "翻炒", "炖煮", "蒸", "烤", "煎", "炸", "烘焙", "面团", "发酵", "打发", "蛋白", "奶油", "黄油", "糖", "面粉", "烤箱", "模具", "裱花", "装饰", "中餐", "川菜", "粤菜", "鲁菜", "淮扬菜", "西餐", "法餐", "意餐", "日料", "寿司", "拉面", "甜点", "蛋糕", "饼干", "布丁", "冰淇淋", "食谱", "菜单", "摆盘", "拍照"],
        "semantic": ["cooking", "baking", "ingredient", "seasoning", "knife skill", "heat", "oil temperature", "stir-fry", "braise", "steam", "roast", "pan-fry", "deep-fry", "dough", "fermentation", "whipping", "egg white", "cream", "butter", "sugar", "flour", "oven", "mold", "piping", "decoration", "Chinese cuisine", "Sichuan", "Cantonese", "Shandong", "Huaiyang", "Western cuisine", "French", "Italian", "Japanese", "sushi", "ramen", "dessert", "cake", "cookie", "pudding", "ice cream", "recipe", "menu", "plating", "food photography"],
        "structure": ["食材-处理-烹饪结构", "配方-步骤-成品结构", "摆盘-拍照-分享结构"],
    },
    {
        "patterns": ["home organization", "tidying", "收纳", "整理", "断舍离", "极简", "家居", "清洁", "打扫"],
        "support": ["收纳", "整理", "分类", "丢弃", "捐赠", "断舍离", "极简", "空间", "衣柜", "厨房", "书房", "客厅", "卧室", "卫生间", "储物", "盒子", "篮子", "架子", "挂钩", "标签", "清洁", "打扫", "除尘", "拖地", "擦窗", "洗衣", "熨烫", "消毒", "除螨", "香薰", "绿植", "装饰", "布置", "软装", "家居", "家具", "灯具", "窗帘", "地毯", "抱枕"],
        "semantic": ["organization", "tidying", "classification", "discard", "donate", "decluttering", "minimalism", "space", "wardrobe", "kitchen", "study", "living room", "bedroom", "bathroom", "storage", "box", "basket", "shelf", "hook", "label", "cleaning", "dusting", "mopping", "window cleaning", "laundry", "ironing", "disinfection", "mite removal", "aromatherapy", "plant", "decoration", "arrangement", "soft decoration", "furniture", "lighting", "curtain", "carpet", "cushion"],
        "structure": ["分类-取舍-归位结构", "空间-功能-美学结构", "清洁-维护-更新结构"],
    },
    {
        "patterns": ["personal finance", "investing", "理财", "投资", "基金", "股票", "债券", "保险", "储蓄", "预算"],
        "support": ["理财", "收入", "支出", "预算", "记账", "储蓄", "应急金", "保险", "重疾险", "医疗险", "意外险", "寿险", "投资", "基金", "股票", "债券", "黄金", "房地产", "REITs", "ETF", "指数基金", "定投", "复利", "风险", "收益", "回撤", "波动", "分散", "资产配置", "再平衡", "税务", "养老", "教育金", "财务自由", "被动收入"],
        "semantic": ["personal finance", "income", "expense", "budget", "bookkeeping", "savings", "emergency fund", "insurance", "critical illness", "medical", "accident", "life insurance", "investment", "fund", "stock", "bond", "gold", "real estate", "REITs", "ETF", "index fund", "DCA", "compound interest", "risk", "return", "drawdown", "volatility", "diversification", "asset allocation", "rebalancing", "tax", "retirement", "education fund", "financial freedom", "passive income"],
        "structure": ["收入-支出-预算结构", "风险-收益-配置结构", "目标-计划-执行结构"],
    },
    {
        "patterns": ["driving", "driver's license", "驾驶", "考驾照", "科目一", "科目二", "科目三", "科目四", "学车", "开车"],
        "support": ["驾照", "科目一", "理论", "法规", "标志", "标线", "信号灯", "科目二", "倒车入库", "侧方停车", "坡道起步", "直角转弯", "曲线行驶", "科目三", "路考", "起步", "变道", "超车", "掉头", "靠边停车", "灯光", "科目四", "安全文明", "学车", "教练", "练车", "场地", "考试", "约考", "挂科", "补考", "实习", "上路", "高速", "停车", "保养", "维修", "保险", "事故", "理赔"],
        "semantic": ["driver's license", "subject 1", "theory", "regulation", "sign", "marking", "traffic light", "subject 2", "reverse parking", "side parking", "hill start", "right-angle turn", "curve driving", "subject 3", "road test", "start", "lane change", "overtaking", "U-turn", "parking", "light", "subject 4", "safety", "driving school", "coach", "practice", "test site", "exam", "booking", "fail", "retake", "probation", "driving", "highway", "parking", "maintenance", "repair", "insurance", "accident", "claim"],
        "structure": ["理论-模拟-考试结构", "操作-练习-熟练结构", "上路-规则-安全结构"],
    },

    # ===== 游戏与电竞（4条） =====
    {
        "patterns": ["MOBA", "League of Legends", "DOTA", "王者荣耀", "英雄联盟", "团战", "排位", "上分"],
        "support": ["MOBA", "英雄", "角色", "技能", "装备", "符文", "天赋", "对线", "补刀", "视野", "地图", "团战", "Gank", "推塔", "兵线", "野区", "Buff", "大龙", "小龙", "排位", "段位", "上分", "匹配", "Ban", "Pick", "阵容", "克制", "配合", "意识", "操作", "走位", "连招", "微操", "复盘", "攻略", "版本", "更新", "赛事", "LPL", "KPL", "S赛"],
        "semantic": ["MOBA", "hero", "champion", "skill", "item", "rune", "talent", "laning", "last hit", "vision", "map", "team fight", "Gank", "push", "minion wave", "jungle", "Buff", "Baron", "Dragon", "ranked", "tier", "climbing", "matchmaking", "Ban", "Pick", "composition", "counter", "cooperation", "awareness", "mechanics", "positioning", "combo", "micro", "review", "guide", "patch", "update", "tournament", "LPL", "KPL", "Worlds"],
        "structure": ["选角-对线-团战结构", "经济-装备-推进结构", "复盘-学习-提升结构"],
    },
    {
        "patterns": ["FPS", "shooting game", "CS", "Valorant", "PUBG", "APEX", "穿越火线", "射击游戏", "枪法", "瞄准"],
        "support": ["FPS", "射击", "枪械", "步枪", "狙击", "手枪", "冲锋枪", "霰弹枪", "瞄准", "开镜", "腰射", "压枪", "后坐力", "弹道", "爆头", "击杀", "死亡", "KD", "回合", "爆破", "人质", "占点", "吃鸡", "跳伞", "搜刮", "毒圈", "空投", "队友", "配合", "战术", "报点", "投掷物", "烟雾", "闪光", "燃烧", "手雷", "地图", "点位", "架枪", "拉枪", "peek"],
        "semantic": ["FPS", "shooting", "firearm", "rifle", "sniper", "pistol", "SMG", "shotgun", "aim", "ADS", "hip fire", "recoil control", "recoil", "ballistic", "headshot", "kill", "death", "K/D", "round", "bomb", "hostage", "control point", "battle royale", "parachute", "loot", "safe zone", "airdrop", "teammate", "cooperation", "tactics", "callout", "grenade", "smoke", "flash", "molotov", "frag", "map", "position", "hold angle", "flick", "peek"],
        "structure": ["瞄准-射击-移动结构", "战术-配合-信息结构", "复盘-训练-提升结构"],
    },
    {
        "patterns": ["single player", "console game", "单机游戏", "主机游戏", "RPG", "AVG", "ACT", "冒险", "剧情"],
        "support": ["单机", "主机", "PC", "PS5", "Xbox", "Switch", "RPG", "JRPG", "WRPG", "AVG", "文字冒险", "视觉小说", "ACT", "动作", "平台", "解谜", "潜行", "恐怖", "生存", "沙盒", "开放世界", "剧情", "叙事", "角色", "成长", "装备", "技能", "任务", "支线", "主线", "结局", "多结局", "成就", "收集", "探索", "地图", "MOD", "二周目", "速通", "攻略", "评测"],
        "semantic": ["single player", "console", "PC", "PS5", "Xbox", "Switch", "RPG", "JRPG", "WRPG", "AVG", "visual novel", "ACT", "action", "platformer", "puzzle", "stealth", "horror", "survival", "sandbox", "open world", "story", "narrative", "character", "growth", "equipment", "skill", "quest", "side quest", "main quest", "ending", "multiple endings", "achievement", "collection", "exploration", "map", "MOD", "NG+", "speedrun", "guide", "review"],
        "structure": ["剧情-探索-战斗结构", "角色-成长-装备结构", "任务-选择-结局结构"],
    },
    {
        "patterns": ["strategy game", "simulation game", "策略游戏", "模拟经营", "SLG", "RTS", "4X", "塔防", "养成"],
        "support": ["策略", "战术", "运营", "经济", "资源", "人口", "科技", "建筑", "单位", "兵种", "克制", "地形", "视野", " fog", "回合", "即时", "微操", "宏操", "多线", "侦查", "骚扰", "正面", "牵制", "模拟", "经营", "城市", "农场", "工厂", "公司", "运输", "规划", "布局", "效率", "利润", "满意度", "事件", "随机", "MOD", "存档", "读档", "S/L"],
        "semantic": ["strategy", "tactics", "operation", "economy", "resource", "population", "technology", "building", "unit", "troop", "counter", "terrain", "vision", "fog of war", "turn-based", "real-time", "micro", "macro", "multi-task", "scout", "harass", "frontal", "diversion", "simulation", "management", "city", "farm", "factory", "company", "transport", "planning", "layout", "efficiency", "profit", "satisfaction", "event", "random", "MOD", "save", "load", "S/L"],
        "structure": ["资源-建设-扩张结构", "战术-操作-微操结构", "规划-经营-优化结构"],
    },

    # ===== 社交与求职（5条） =====
    {
        "patterns": ["social skills", "communication", "社交技巧", "人际关系", "沟通", "情商", "表达", "倾听"],
        "support": ["社交", "沟通", "表达", "倾听", "反馈", "提问", "赞美", "批评", "拒绝", "谈判", "说服", "影响力", "情商", "情绪", "同理心", "换位思考", "非暴力沟通", "积极倾听", "开放式问题", "封闭式问题", "身体语言", "眼神", "微笑", "姿态", "距离", "场合", "礼仪", "介绍", "寒暄", "话题", "聊天", " Networking", "人脉", "圈子", "社群", "活动", "聚会", "饭局", "约会"],
        "semantic": ["social skills", "communication", "expression", "listening", "feedback", "question", "praise", "criticism", "refusal", "negotiation", "persuasion", "influence", "EQ", "emotion", "empathy", "perspective-taking", "nonviolent communication", "active listening", "open question", "closed question", "body language", "eye contact", "smile", "posture", "distance", "occasion", "etiquette", "introduction", "small talk", "topic", "chat", "networking", "connection", "circle", "community", "event", "party", "dinner", "date"],
        "structure": ["观察-倾听-回应结构", "表达-反馈-调整结构", "建立-维护-深化结构"],
    },
    {
        "patterns": ["dating", "relationship", "恋爱", "情感", "亲密关系", "约会", "相亲", "婚姻"],
        "support": ["恋爱", "喜欢", "好感", "吸引", "追求", "表白", "约会", "相处", "沟通", "信任", "尊重", "理解", "包容", "陪伴", "支持", "共同成长", "冲突", "矛盾", "冷战", "分手", "复合", "挽回", "相亲", "条件", "门当户对", "婚姻", "婚前", "婚后", "家庭", "亲子", "亲密关系", "依恋", "安全感", "边界", "独立", "依赖"],
        "semantic": ["dating", "relationship", "intimacy", "affection", "attraction", "pursuit", "confession", "date", "getting along", "communication", "trust", "respect", "understanding", "tolerance", "companionship", "support", "mutual growth", "conflict", "contradiction", "cold war", "breakup", "reconciliation", "recovery", "blind date", "condition", "match", "marriage", "pre-marriage", "post-marriage", "family", "parenting", "attachment", "security", "boundary", "independence", "dependence"],
        "structure": ["认识-了解-相处结构", "沟通-冲突-解决结构", "规划-承诺-经营结构"],
    },
    {
        "patterns": ["job interview", "求职", "面试", "校招", "社招", "实习", "简历", "HR", "offer"],
        "support": ["求职", "简历", "CV", "求职信", "cover letter", "投递", "网申", "内推", "笔试", "面试", "群面", "单面", "HR面", "技术面", "主管面", "终面", "压力面", "案例面", "行为面试", "STAR法则", "自我介绍", "优缺点", "职业规划", "期望薪资", "离职原因", "反问", "跟进", "offer", "拒信", "背调", "入职", "试用期", "转正", "跳槽", "裸辞", "gap", "校招", "秋招", "春招", "社招", "猎头"],
        "semantic": ["job interview", "job hunting", "resume", "CV", "cover letter", "application", "online application", "referral", "written test", "interview", "group interview", "individual interview", "HR interview", "technical interview", "manager interview", "final interview", "stress interview", "case interview", "behavioral interview", "STAR method", "self-introduction", "strength", "weakness", "career plan", "expected salary", "reason for leaving", "Q&A", "follow-up", "offer", "rejection", "background check", "onboarding", "probation", "confirmation", "job hop", "quit", "gap", "campus recruitment", "fall recruitment", "spring recruitment", "social recruitment", "headhunter"],
        "structure": ["准备-表现-跟进结构", "问题-回答-展示结构", "投递-面试-入职结构"],
    },
    {
        "patterns": ["public speaking", "debate", "eloquence", "演讲", "辩论", "口才", "即兴演讲", "TED", "路演"],
        "support": ["演讲", "演讲稿", "开场", "主体", "结尾", "故事", "数据", "案例", "金句", "幽默", "互动", "提问", "呼吁", "行动", "PPT", "视觉", "声音", "语速", "语调", "停顿", "重音", "眼神", "手势", "站姿", "走位", "紧张", "放松", "排练", "辩论", "立论", "质询", "驳论", "总结", "自由辩", "团队", "配合", "战术", "资料", "论据", "逻辑", "修辞", "说服", "感染"],
        "semantic": ["public speaking", "speech", "opening", "body", "ending", "story", "data", "case", "quote", "humor", "interaction", "question", "call to action", "PPT", "visual", "voice", "speech rate", "intonation", "pause", "stress", "eye contact", "gesture", "posture", "movement", "nervousness", "relaxation", "rehearsal", "debate", "constructive", "cross-examination", "rebuttal", "summary", "free debate", "team", "cooperation", "tactics", "material", "evidence", "logic", "rhetoric", "persuasion", "inspiration"],
        "structure": ["准备-排练-呈现结构", "论点-论据-论证结构", "开场-推进-收束结构"],
    },
    {
        "patterns": ["networking", "personal branding", "人脉", "社交圈", "个人品牌", "影响力", "领导力", "社群运营"],
        "support": ["人脉", "关系", "连接", "互助", "价值", "信任", "口碑", "推荐", "介绍", "个人品牌", "定位", "形象", "内容", "平台", "曝光", "互动", "粉丝", "关注", "影响力", "KOL", "KOC", "意见领袖", "领导力", "愿景", "激励", "团队", "文化", "决策", "执行", "反馈", "复盘", "社群", "运营", "规则", "活动", "内容", "用户", "活跃", "转化", "变现"],
        "semantic": ["networking", "connection", "relationship", "mutual help", "value", "trust", "reputation", "recommendation", "introduction", "personal brand", "positioning", "image", "content", "platform", "exposure", "interaction", "follower", "influence", "KOL", "KOC", "thought leader", "leadership", "vision", "motivation", "team", "culture", "decision-making", "execution", "feedback", "review", "community", "operation", "rule", "activity", "user", "activity rate", "conversion", "monetization"],
        "structure": ["定位-内容-传播结构", "互动-信任-合作结构", "愿景-行动-影响结构"],
    },

    # ===== 旅行与户外（4条） =====
    {
        "patterns": ["travel planning", "旅游", "旅行", "自由行", "跟团", "背包客", "攻略", " itinerary"],
        "support": ["旅行", "目的地", "景点", "路线", "交通", "机票", "火车", "汽车", "船", "住宿", "酒店", "民宿", "青旅", "露营", "美食", "餐厅", "小吃", "购物", "预算", "签证", "护照", "保险", "攻略", "游记", "打卡", "拍照", "人文", "自然", "历史", "艺术", "探险", "休闲", "度假", "蜜月", "亲子", "独自旅行", "结伴", "约伴"],
        "semantic": ["travel", "destination", "attraction", "route", "transportation", "flight", "train", "bus", "ferry", "accommodation", "hotel", "homestay", "hostel", "camping", "food", "restaurant", "snack", "shopping", "budget", "visa", "passport", "insurance", "guide", "travelogue", "check-in", "photography", "culture", "nature", "history", "art", "adventure", "leisure", "vacation", "honeymoon", "family trip", "solo travel", "group travel", "travel buddy"],
        "structure": ["目的地-路线-预算结构", "交通-住宿-活动结构", "体验-记录-分享结构"],
    },
    {
        "patterns": ["hiking", "mountaineering", "徒步", "登山", "攀岩", "越野", "户外探险"],
        "support": ["徒步", "登山", "攀岩", "攀冰", "越野", "穿越", "探险", "路线", "轨迹", "海拔", "爬升", "下降", "距离", "时间", "速度", "负重", "背包", "帐篷", "睡袋", "防潮垫", "炉具", "食物", "水", "导航", "地图", "GPS", "指南针", "天气", "季节", "风险", "安全", "急救", "保险", "体能", "训练", "装备", "鞋子", "服装", "Layer", "团队", "领队", "协作", "LNT", "无痕山林"],
        "semantic": ["hiking", "mountaineering", "rock climbing", "ice climbing", "trail running", "crossing", "exploration", "route", "track", "altitude", "elevation gain", "descent", "distance", "time", "speed", "load", "backpack", "tent", "sleeping bag", "pad", "stove", "food", "water", "navigation", "map", "GPS", "compass", "weather", "season", "risk", "safety", "first aid", "insurance", "fitness", "training", "gear", "shoes", "clothing", "layer", "team", "leader", "cooperation", "LNT", "Leave No Trace"],
        "structure": ["规划-准备-执行结构", "路线-导航-安全结构", "体能-技能-装备结构"],
    },
    {
        "patterns": ["camping", "outdoor survival", "露营", "野外生存", "野营", "房车", "Glamping"],
        "support": ["露营", "帐篷", "天幕", "睡袋", "床垫", "桌椅", "灯具", "炉具", "炊具", "食材", "烧烤", "篝火", "野外", "生存", "取水", "净水", "取火", "搭建", "庇护所", "方向", "求救", "信号", "急救", "包扎", "绳结", "刀具", "多功能工具", "房车", "Glamping", "精致露营", "风格", "氛围", "装饰", "拍照", "社交", "聚会", "亲子", "宠物"],
        "semantic": ["camping", "tent", "tarp", "sleeping bag", "mattress", "chair", "table", "lamp", "stove", "cookware", "ingredient", "BBQ", "bonfire", "wilderness", "survival", "water source", "water purification", "fire making", "shelter", "direction", "rescue", "signal", "first aid", "bandage", "knot", "knife", "multi-tool", "RV", "Glamping", "luxury camping", "style", "atmosphere", "decoration", "photography", "social", "gathering", "family", "pet"],
        "structure": ["选址-搭建-活动结构", "生存-安全-应急结构", "氛围-体验-社交结构"],
    },
    {
        "patterns": ["travel photography", "vlog", "旅拍", "旅行视频", "vlog", "航拍", "无人机", "GoPro"],
        "support": ["旅拍", "旅行", "摄影", "视频", "vlog", "航拍", "无人机", "DJI", "GoPro", "运动相机", "稳定器", "云台", "剪辑", "调色", "音乐", "字幕", "转场", "故事", "叙事", "节奏", "景点", "人文", "美食", "住宿", "交通", "攻略", "分享", "平台", "B站", "YouTube", "小红书", "抖音", "粉丝", "播放", "点赞", "收藏", "评论", "商单", "变现"],
        "semantic": ["travel photography", "travel video", "vlog", "aerial photography", "drone", "DJI", "GoPro", "action camera", "stabilizer", "gimbal", "editing", "color grading", "music", "subtitle", "transition", "story", "narrative", "pacing", "attraction", "culture", "food", "accommodation", "transportation", "guide", "sharing", "platform", "Bilibili", "YouTube", "Xiaohongshu", "Douyin", "follower", "view", "like", "bookmark", "comment", "brand deal", "monetization"],
        "structure": ["行程-拍摄-剪辑结构", "故事-节奏-音乐结构", "发布-互动-运营结构"],
    },

    # ===== 手工与爱好（4条） =====
    {
        "patterns": ["painting", "illustration", "drawing", "绘画", "插画", "素描", "水彩", "油画", "国画", "procreate"],
        "support": ["绘画", "素描", "速写", "水彩", "油画", "丙烯", "国画", "工笔", "写意", "白描", "插画", "原画", "概念", "角色", "场景", "漫画", "动画", "分镜", "Procreate", "Photoshop", "SAI", "CSP", "笔触", "线条", "明暗", "色彩", "构图", "透视", "比例", "动态", "表情", "质感", "临摹", "写生", "创作", "风格", "流派", "展览", "参赛", "接单", "约稿"],
        "semantic": ["painting", "sketch", "quick sketch", "watercolor", "oil painting", "acrylic", "Chinese painting", "gongbi", "xieyi", "line drawing", "illustration", "concept art", "character", "scene", "comic", "animation", "storyboard", "Procreate", "Photoshop", "SAI", "CSP", "brushstroke", "line", "light and shadow", "color", "composition", "perspective", "proportion", "dynamic", "expression", "texture", "copying", "sketching from life", "creation", "style", "school", "exhibition", "competition", "commission", "request"],
        "structure": ["观察-构图-刻画结构", "临摹-写生-创作结构", "草图-细化-完成结构"],
    },
    {
        "patterns": ["DIY", "handicraft", "crafts", "手工", "DIY", "黏土", "羊毛毡", "滴胶", "编织", "刺绣"],
        "support": ["手工", "DIY", "黏土", "软陶", "超轻黏土", "石塑黏土", "羊毛毡", "戳戳乐", "滴胶", "UV胶", "环氧树脂", "模具", "配色", "装饰", "编织", "钩针", "棒针", "毛线", "棉线", "麻绳", "Macrame", "刺绣", "十字绣", "法式刺绣", "珠绣", "丝带绣", "布艺", "拼布", "缝纫", "皮具", "木工", "金工", "首饰", "滴蜡", "蜡烛", "香薰", "皂", "模型", "纸艺", "折纸", "剪纸", "衍纸", "热缩片"],
        "semantic": ["handicraft", "DIY", "clay", "polymer clay", "light clay", "stone clay", "needle felting", "wet felting", "resin", "UV resin", "epoxy", "mold", "color matching", "decoration", "weaving", "crochet", "knitting", "yarn", "cotton thread", "hemp rope", "Macrame", "embroidery", "cross-stitch", "French embroidery", "bead embroidery", "ribbon embroidery", "fabric", "quilting", "sewing", "leather", "woodworking", "metalwork", "jewelry", "wax", "candle", "aromatherapy", "soap", "model", "paper craft", "origami", "paper cutting", "quilling", "shrink plastic"],
        "structure": ["设计-制作-完善结构", "材料-工具-技法结构", "灵感-尝试-成品结构"],
    },
    {
        "patterns": ["instrument", "music performance", "乐器", "演奏", "钢琴", "吉他", "小提琴", "架子鼓", "古筝"],
        "support": ["乐器", "钢琴", "吉他", "小提琴", "中提琴", "大提琴", "低音提琴", "长笛", "单簧管", "双簧管", "萨克斯", "小号", "长号", "圆号", "架子鼓", "打击乐", "古筝", "古琴", "琵琶", "二胡", "笛子", "箫", "葫芦丝", "尤克里里", "口琴", "手风琴", "电子琴", "合成器", "乐理", "识谱", "视唱", "练耳", "音阶", "琶音", "和弦", "节奏", "技巧", "指法", "弓法", "气息", "练习曲", "乐曲", "考级", "演出", "合奏", "伴奏", "即兴"],
        "semantic": ["instrument", "piano", "guitar", "violin", "viola", "cello", "double bass", "flute", "clarinet", "oboe", "saxophone", "trumpet", "trombone", "French horn", "drum kit", "percussion", "guzheng", "guqin", "pipa", "erhu", "dizi", "xiao", "hulusi", "ukulele", "harmonica", "accordion", "electronic keyboard", "synthesizer", "music theory", "sight-reading", "solfege", "ear training", "scale", "arpeggio", "chord", "rhythm", "technique", "fingering", "bowing", "breath", "etude", "piece", "grading exam", "performance", "ensemble", "accompaniment", "improvisation"],
        "structure": ["基础-技巧-乐曲结构", "练习-回课-提升结构", "独奏-合奏-表演结构"],
    },
    {
        "patterns": ["board game", "chess", "棋类", "桌游", "围棋", "象棋", "国际象棋", "扑克", "麻将", "剧本杀"],
        "support": ["围棋", "布局", "定式", "中盘", "官子", "计算", "死活", "手筋", "形势判断", "象棋", "开局", "中局", "残局", "杀法", "战术", "国际象棋", " openings", "战术", "残局", "策略", "扑克", "德州", "概率", "心理", "读人", "麻将", "规则", "番种", "策略", "运气", "桌游", "德式", "美式", "合作", "对抗", "跑团", "D&D", "COC", "剧本杀", "推理", "角色", "沉浸", "社交"],
        "semantic": ["Go", "opening", "joseki", "middlegame", "endgame", "reading", "life and death", "tesuji", "positional judgment", "Chinese chess", "opening", "middlegame", "endgame", "tactics", "chess", "openings", "tactics", "endgame", "strategy", "poker", "Texas Hold'em", "probability", "psychology", "tell", "mahjong", "rule", "scoring", "strategy", "luck", "board game", "Eurogame", "Ameritrash", "cooperative", "competitive", "TRPG", "D&D", "COC", "murder mystery game", "deduction", "role", "immersion", "social"],
        "structure": ["规则-策略-执行结构", "计算-判断-决策结构", "角色-推理-互动结构"],
    },

    # ===== 影视与娱乐（5条） =====
    {
        "patterns": ["movie", "film review", "看电影", "影评", "电影分析", "导演研究", "类型片", "电影节"],
        "support": ["电影", "院线", "流媒体", "Netflix", "导演", "演员", "剧本", "摄影", "剪辑", "配乐", "美术", "类型", "剧情", "喜剧", "动作", "科幻", "恐怖", "悬疑", "爱情", "文艺", "纪录片", "动画", "影评", "分析", "解读", "拉片", "视听语言", "镜头", "场面调度", "蒙太奇", "长镜头", "叙事", "主题", "符号", "隐喻", "电影节", "奥斯卡", "戛纳", "柏林", "威尼斯"],
        "semantic": ["movie", "film", "theatrical release", "streaming", "Netflix", "director", "actor", "screenplay", "cinematography", "editing", "score", "art direction", "genre", "drama", "comedy", "action", "sci-fi", "horror", "thriller", "romance", "art film", "documentary", "animation", "film review", "analysis", "interpretation", "scene-by-scene", "film language", "shot", "mise-en-scene", "montage", "long take", "narrative", "theme", "symbol", "metaphor", "film festival", "Oscar", "Cannes", "Berlin", "Venice"],
        "structure": ["观看-记录-分析结构", "视听-叙事-主题结构", "比较-评价-写作结构"],
    },
    {
        "patterns": ["TV series", "variety show", "追剧", "综艺", "电视剧", "网剧", "韩剧", "美剧", "日剧", "国产剧"],
        "support": ["电视剧", "网剧", "韩剧", "美剧", "日剧", "英剧", "泰剧", "国产剧", "古装", "现代", "悬疑", "爱情", "职场", "家庭", "历史", "科幻", "动漫", "追剧", "更新", "季", "集", "番", "弹幕", "评论", "讨论", "剧透", "避雷", "安利", "综艺", "真人秀", "选秀", "竞演", "访谈", "脱口秀", "美食", "旅行", "竞技", "游戏", "慢综艺", "恋综", "观察室", "嘉宾", "MC"],
        "semantic": ["TV series", "web drama", "K-drama", "American drama", "J-drama", "British drama", "Thai drama", "Chinese drama", "costume", "modern", "mystery", "romance", "workplace", "family", "history", "sci-fi", "anime", "binge-watching", "update", "season", "episode", "danmaku", "comment", "discussion", "spoiler", "avoid", "recommendation", "variety show", "reality show", "talent show", "competition", "interview", "talk show", "food", "travel", "sports", "game show", "slow variety", "dating show", "observation room", "guest", "MC"],
        "structure": ["观看-讨论-评价结构", "剧情-角色-制作结构", "娱乐-社交-消费结构"],
    },
    {
        "patterns": ["fandom", "celebrity", "追星", "饭圈", " idol", "应援", "打榜", "控评"],
        "support": ["追星", "偶像", "明星", "演员", "歌手", "爱豆", "男团", "女团", "solo", "作品", "专辑", "单曲", "MV", "演唱会", "见面会", "签售", "应援", "灯牌", "手幅", "周边", "小卡", "pb", "打榜", "投票", "刷管", "控评", "反黑", "净化", "站子", "大粉", "散粉", "cp", "唯粉", "团粉", "泥塑", "整肃", "同人", "产出", "剪辑", "修图", "文案", "撕逼", "互撕", "脱粉", "回踩", "塌房"],
        "semantic": ["fandom", "idol", "celebrity", "star", "actor", "singer", "idol", "boy group", "girl group", "solo", "work", "album", "single", "MV", "concert", "fan meeting", "fansign", "support", "light board", "banner", "merchandise", "photocard", "photo book", "charting", "voting", "streaming", "comment control", "anti-hate", "cleanup", "fan site", "big fan", "casual fan", "cp", "solo stan", "group stan", "fan fiction", "creation", "editing", "photo editing", "copywriting", "fan war", "unstan", "anti", "scandal"],
        "structure": ["关注-消费-参与结构", "应援-产出-传播结构", "社群-规范-冲突结构"],
    },
    {
        "patterns": ["anime", "manga", "二次元", "动漫", "动画", "漫画", "轻小说", "cosplay", "手办", "番剧"],
        "support": ["动漫", "动画", "漫画", "番剧", "新番", "季番", "年番", "剧场版", "OVA", "OAD", "轻小说", "web小说", "同人", "cosplay", "手办", "周边", "谷子", "吧唧", "立牌", "色纸", "抱枕", "漫展", "Comiket", "CP", "B站", "追番", "补番", "N刷", "弹幕", "评论", "up主", "MAD", "AMV", "MMD", "vocaloid", "初音", "舰娘", "型月", "高达", "EVA", "鬼灭", "咒术", "间谍", "电锯", "京阿尼"],
        "semantic": ["anime", "animation", "manga", "series", "new season", "seasonal", "yearly", "movie", "OVA", "OAD", "light novel", "web novel", "doujin", "cosplay", "figure", "merchandise", "badge", "acrylic stand", "shikishi", "dakimakura", "anime convention", "Comiket", "CP", "Bilibili", "watchlist", "catch-up", "rewatch", "danmaku", "comment", "up主", "MAD", "AMV", "MMD", "Vocaloid", "Hatsune Miku", "Kantai Collection", "Type-Moon", "Gundam", "EVA", "Demon Slayer", "Jujutsu Kaisen", "Spy Family", "Chainsaw Man", "Kyoto Animation"],
        "structure": ["观看-讨论-创作结构", "角色-剧情-世界观结构", "消费-收藏-社交结构"],
    },
    {
        "patterns": ["documentary", "科普", "纪录片", "自然", "历史", "人文", "Discovery", "BBC", "国家地理"],
        "support": ["纪录片", "自然", "动物", "植物", "生态", "地理", "天文", "宇宙", "物理", "化学", "生物", "历史", "考古", "文明", "战争", "政治", "经济", "社会", "人文", "艺术", "音乐", "美食", "旅行", "探险", "科普", "知识", "科学", "技术", "工程", "数学", "医学", "健康", "心理", "教育", "Discovery", "BBC", "国家地理", "NHK", "CCTV", "B站", "弹幕", "评论", "笔记", "截图"],
        "semantic": ["documentary", "nature", "animal", "plant", "ecology", "geography", "astronomy", "universe", "physics", "chemistry", "biology", "history", "archaeology", "civilization", "war", "politics", "economy", "society", "humanities", "art", "music", "food", "travel", "expedition", "science popularization", "knowledge", "science", "technology", "engineering", "mathematics", "medicine", "health", "psychology", "education", "Discovery", "BBC", "National Geographic", "NHK", "CCTV", "Bilibili", "danmaku", "comment", "note", "screenshot"],
        "structure": ["观看-记录-思考结构", "事实-解释-启示结构", "知识-传播-讨论结构"],
    },

    # ===== 阅读与知识（4条） =====
    {
        "patterns": ["reading", "book", "读书", "阅读", "书评", "读书笔记", "kindle", "微信读书", "豆瓣"],
        "support": ["读书", "阅读", "书籍", "小说", "非虚构", "传记", "历史", "哲学", "科学", "经济", "管理", "心理学", "文学", "艺术", "设计", "技术", "编程", "自我提升", "工具书", "教材", "参考书", "kindle", "电子书", "纸质书", "图书馆", "书店", "书单", "推荐", "评分", "豆瓣", " Goodreads", "书评", "读后感", "笔记", "摘抄", "思维导图", "主题阅读", "对比阅读", "精读", "泛读", "速读", "听书", "播客"],
        "semantic": ["reading", "book", "novel", "non-fiction", "biography", "history", "philosophy", "science", "economy", "management", "psychology", "literature", "art", "design", "technology", "programming", "self-improvement", "reference book", "textbook", "e-book", "paper book", "library", "bookstore", "book list", "recommendation", "rating", "Douban", "Goodreads", "book review", "reading note", "excerpt", "mind map", "thematic reading", "comparative reading", "intensive reading", "extensive reading", "speed reading", "audiobook", "podcast"],
        "structure": ["选书-阅读-笔记结构", "理解-思考-应用结构", "输入-整理-输出结构"],
    },
    {
        "patterns": ["knowledge management", "note-taking", "知识管理", "笔记", "obsidian", "notion", "roam research", "flomo", "思维导图"],
        "support": ["知识", "信息", "收集", "整理", "分类", "标签", "链接", "关联", "检索", "回顾", "复习", "输出", "笔记", "摘录", "批注", "卡片", "大纲", "思维导图", "流程图", "概念图", "Obsidian", "Notion", "Roam", "Flomo", "印象笔记", "有道云", "语雀", "石墨", "飞书", "维基", "知识库", "第二大脑", "Zettelkasten", "PARA", "GTD", "费曼技巧", "间隔重复", "Anki", "SuperMemo"],
        "semantic": ["knowledge", "information", "collection", "organization", "classification", "tag", "link", "connection", "retrieval", "review", "revision", "output", "note", "excerpt", "annotation", "card", "outline", "mind map", "flowchart", "concept map", "Obsidian", "Notion", "Roam", "Flomo", "Evernote", "Youdao", "Yuque", "Shimo", "Feishu", "wiki", "knowledge base", "second brain", "Zettelkasten", "PARA", "GTD", "Feynman technique", "spaced repetition", "Anki", "SuperMemo"],
        "structure": ["收集-整理-连接结构", "理解-记忆-回顾结构", "输入-加工-输出结构"],
    },
    {
        "patterns": ["podcast", "audiobook", "播客", "有声书", "得到", "喜马拉雅", "小宇宙", "知识付费", "课程"],
        "support": ["播客", "单口", "对谈", "访谈", "专题", "系列", "音频", "声音", "主持", "嘉宾", "话题", "观点", "分析", "故事", "有声书", "朗读", "配音", "演绎", "得到", "喜马拉雅", "小宇宙", "知识付费", "课程", "专栏", "训练营", "直播课", "录播课", "学习", "笔记", "总结", "实践", "社群", "打卡", "作业", "证书", "认知", "思维", "方法", "工具", "效率", "成长"],
        "semantic": ["podcast", "monologue", "conversation", "interview", "topic", "series", "audio", "voice", "host", "guest", "subject", "opinion", "analysis", "story", "audiobook", "reading", "dubbing", "performance", "Dedao", "Ximalaya", "Xiaoyuzhou", "knowledge payment", "course", "column", "bootcamp", "live class", "recorded class", "learning", "note", "summary", "practice", "community", "check-in", "assignment", "certificate", "cognition", "thinking", "method", "tool", "efficiency", "growth"],
        "structure": ["收听-笔记-思考结构", "课程-学习-实践结构", "认知-方法-行动结构"],
    },
    {
        "patterns": ["science popularization", "popular science", "科普", "知识", "通识", "终身学习", "跨界学习"],
        "support": ["科普", "科学", "物理", "化学", "生物", "天文", "地理", "数学", "计算机", "工程", "医学", "心理", "经济", "社会", "历史", "哲学", "艺术", "通识", "跨学科", "交叉", "融合", "终身学习", "成长", "认知", "思维", "逻辑", "批判", "创新", "好奇心", "问题", "探索", "发现", "实验", "验证", "证据", "理性", "怀疑", "开放", "谦逊"],
        "semantic": ["science popularization", "science", "physics", "chemistry", "biology", "astronomy", "geography", "mathematics", "computer", "engineering", "medicine", "psychology", "economy", "society", "history", "philosophy", "art", "general education", "interdisciplinary", "integration", "lifelong learning", "growth", "cognition", "thinking", "logic", "critical thinking", "innovation", "curiosity", "question", "exploration", "discovery", "experiment", "verification", "evidence", "rationality", "skepticism", "openness", "humility"],
        "structure": ["问题-探索-解答结构", "输入-整合-输出结构", "学习-思考-行动结构"],
    },

    # ===== 创业与商业（2条） =====
    {
        "patterns": ["entrepreneurship", "startup", "创业", "开公司", "做生意", "合伙人", "商业计划", "融资", "路演", "天使投资", "VC", "孵化器", "加速器"],
        "support": ["创业", "公司", "企业", "商业", "市场", "产品", "服务", "用户", "客户", "需求", "痛点", "解决方案", "商业模式", "盈利模式", "收入", "成本", "利润", "现金流", "融资", "投资", "股权", "期权", "合伙人", "团队", "招聘", "管理", "运营", "增长", "获客", "留存", "变现", "路演", "Pitch", "BP", "MVP", "PMF", "迭代", "验证", "假设", "实验", "数据", "指标", "OKR", "KPI", "品牌", "营销", "公关", "法务", "财务", "税务", "工商", "注册", "知识产权", "专利", "商标"],
        "semantic": ["entrepreneurship", "startup", "company", "business", "market", "product", "service", "user", "customer", "need", "pain point", "solution", "business model", "profit model", "revenue", "cost", "profit", "cash flow", "financing", "investment", "equity", "option", "partner", "team", "recruit", "manage", "operate", "growth", "acquisition", "retention", "monetization", "pitch", "roadshow", "BP", "MVP", "PMF", "iterate", "validate", "hypothesis", "experiment", "data", "metrics", "OKR", "KPI", "brand", "marketing", "PR", "legal", "finance", "tax", "registration", "IP", "patent", "trademark"],
        "structure": ["需求-方案-验证结构", "获客-留存-变现结构", "假设-实验-迭代结构"],
    },
    {
        "patterns": ["business plan", "business model", "商业模式", "商业画布", "SWOT", "竞品分析", "市场调研", "用户画像"],
        "support": ["商业", "计划", "模式", "画布", "战略", "战术", "目标", "愿景", "使命", "价值观", "SWOT", "PEST", "五力模型", "价值链", "竞品", "竞争", "对手", "优势", "劣势", "机会", "威胁", "市场", "调研", "问卷", "访谈", "焦点小组", "用户", "画像", " persona", "细分", "定位", "差异化", "定价", "渠道", "推广", "品牌", "漏斗", "转化", "留存", "LTV", "CAC", "ROI", "GMV", "DAU", "MAU", "ARPU"],
        "semantic": ["business plan", "business model", "canvas", "strategy", "tactic", "goal", "vision", "mission", "value", "SWOT", "PEST", "Porter five forces", "value chain", "competitor", "competition", "advantage", "disadvantage", "opportunity", "threat", "market research", "survey", "interview", "focus group", "user persona", "segmentation", "positioning", "differentiation", "pricing", "channel", "promotion", "brand", "funnel", "conversion", "retention", "LTV", "CAC", "ROI", "GMV", "DAU", "MAU", "ARPU"],
        "structure": ["分析-策略-执行结构", "用户-产品-市场结构", "输入-转化-输出结构"],
    },

    # ===== 求职与面试（2条） =====
    {
        "patterns": ["job hunting", "job search", "求职", "找工作", "简历", "面试", "猎头", "招聘会", "春招", "秋招", "社招", "校招"],
        "support": ["求职", "应聘", "招聘", "工作", "职位", "岗位", "JD", "描述", "要求", "职责", "薪资", "待遇", "福利", "五险一金", "公积金", "社保", "年假", "期权", "股票", "简历", "CV", "履历", "经历", "项目", "成果", "业绩", "面试", "笔试", "群面", "HR面", "技术面", "终面", "offer", "录用", "入职", "离职", "跳槽", "转行", "升职", "加薪", "绩效", "考核", "KPI", "OKR", "职业规划", "生涯", "发展", "猎头", "内推", "人脉", "LinkedIn", "Boss直聘", "猎聘", "智联", "前程", "拉勾", "实习僧"],
        "semantic": ["job hunting", "job search", "apply", "recruit", "work", "position", "job description", "requirement", "responsibility", "salary", "benefit", "welfare", "social insurance", "housing fund", "annual leave", "option", "stock", "resume", "CV", "experience", "project", "achievement", "performance", "interview", "written test", "group interview", "HR interview", "technical interview", "final interview", "offer", "hire", "onboard", "resign", "job hop", "career change", "promotion", "raise", "KPI", "OKR", "career planning", "headhunter", "referral", "network", "LinkedIn"],
        "structure": ["岗位-匹配-投递结构", "准备-面试-跟进结构", "现状-目标-行动结构"],
    },
    {
        "patterns": ["interview", "interview skills", "面试技巧", "自我介绍", "STAR法则", "行为面试", "无领导小组", "Case Interview"],
        "support": ["面试", "技巧", "准备", "模拟", "练习", "复盘", "自我介绍", "开场", "结尾", "提问", "回答", "STAR", "情境", "任务", "行动", "结果", "行为", "经历", "案例", "故事", "亮点", "优势", "匹配", "动机", "职业规划", "期望", "薪资谈判", "压薪", "涨薪", "反追问", "压力面", "Case", "案例", "分析", "逻辑", "框架", "结构化", "表达", "沟通", "仪态", "着装", "礼仪", "守时", "自信", "真诚", "谦虚", "积极", "热情", "眼神", "手势", "语速", "语调"],
        "semantic": ["interview", "skill", "preparation", "simulation", "practice", "review", "self introduction", "opening", "closing", "question", "answer", "STAR", "situation", "task", "action", "result", "behavioral", "experience", "case", "story", "highlight", "advantage", "match", "motivation", "career plan", "expectation", "salary negotiation", "raise", "pressure interview", "case interview", "analysis", "logic", "framework", "structure", "expression", "communication", "appearance", "dress code", "etiquette", "punctuality", "confidence", "sincerity", "humility", "enthusiasm"],
        "structure": ["准备-展示-跟进结构", "问题-分析-回答结构", "情境-任务-结果结构"],
    },

    # ===== 公职与考试（1条） =====
    {
        "patterns": ["civil service", "public servant", "公务员", "国考", "省考", "选调生", "事业单位", "编制", "行测", "申论"],
        "support": ["公务员", "公职", "机关", "政府", "行政", "事业单位", "编制", "国考", "省考", "市考", "选调", "遴选", "行测", "言语", "数量", "判断", "资料", "常识", "申论", "阅读", "写作", "公文", "策论", "面试", "结构化", "无领导", "体检", "政审", "公示", "录用", "职级", "晋升", "待遇", "福利", "稳定", "编制", "铁饭碗", "体制", "内", "基层", "乡镇", "街道", "部委", "厅局", "处级", "科级"],
        "semantic": ["civil servant", "public servant", "government", "administration", "public institution", "establishment", "national exam", "provincial exam", "municipal exam", "selection", "screening", "administrative test", "language", "quantity", "judgment", "data", "general knowledge", "essay", "reading", "writing", "official document", "policy essay", "interview", "structured", "leaderless", "physical exam", "political review", "public announcement", "hire", "rank", "promotion", "treatment", "benefit", "stability", "system", "grassroots", "township", "street", "ministry", "department", "bureau", "division", "section"],
        "structure": ["刷题-总结-复盘结构", "阅读-写作-批改结构", "知识-技巧-模拟结构"],
    },

    # ===== 副业与自由职业（1条） =====
    {
        "patterns": ["side hustle", "freelance", "副业", "兼职", "自由职业", "斜杠青年", "接私活", "外包", "Upwork", "Fiverr"],
        "support": ["副业", "兼职", "自由职业", "freelance", "斜杠", "技能", "变现", "接单", "私活", "外包", "项目", "客户", "报价", "合同", "交付", "验收", "收款", "发票", "税务", "平台", "Upwork", "Fiverr", "猪八戒", "一品威客", "站酷", "花瓣", "Behance", "Dribbble", "GitHub", "知乎", "小红书", "抖音", "B站", "公众号", "自媒体", "流量", "粉丝", "广告", "带货", "电商", "开店", "代购", "分销", "代理", "加盟", "投资", "理财", "股票", "基金", "写作", "翻译", "设计", "编程", "咨询", "培训", "家教", "摄影", "剪辑"],
        "semantic": ["side hustle", "part-time", "freelance", "slash", "skill", "monetization", "order", "private job", "outsourcing", "project", "client", "quotation", "contract", "delivery", "acceptance", "payment", "invoice", "tax", "platform", "self-media", "traffic", "follower", "advertisement", "e-commerce", "shop", "purchase agent", "distribution", "agency", "franchise", "investment", "stock", "fund", "writing", "translation", "design", "programming", "consulting", "training", "tutoring", "photography", "editing"],
        "structure": ["技能-产品-变现结构", "获客-交付-复购结构", "平台-内容-流量结构"],
    },

    # ===== 科研与学术（2条） =====
    {
        "patterns": ["research", "academic research", "科研", "学术研究", "课题", "项目", "基金", "论文发表", "SCI", "SSCI", "EI", "影响因子"],
        "support": ["科研", "学术", "研究", "课题", "项目", "基金", "自然科学基金", "社科基金", "横向", "纵向", "实验室", "课题组", "导师", "学生", "博士后", "访问学者", "合作", "交流", "会议", "期刊", "论文", "投稿", "审稿", "修改", "接收", "发表", "SCI", "SSCI", "EI", "CSSCI", "北大核心", "影响因子", "IF", "引用", "h-index", "数据库", "文献", "综述", "meta", "实验", "数据", "统计", "分析", "建模", "仿真", "验证", "假设", "理论", "方法", "技术", "创新", "突破", "成果", "专利", "转化", "报奖", "职称", "青千", "杰青", "长江", "院士"],
        "semantic": ["research", "academic", "study", "project", "fund", "NSFC", "social science fund", "laboratory", "research group", "supervisor", "student", "postdoc", "visiting scholar", "cooperation", "conference", "journal", "paper", "submission", "review", "revision", "acceptance", "publication", "SCI", "SSCI", "EI", "CSSCI", "impact factor", "citation", "h-index", "database", "literature", "review", "meta-analysis", "experiment", "data", "statistics", "analysis", "modeling", "simulation", "validation", "hypothesis", "theory", "method", "technology", "innovation", "breakthrough", "achievement", "patent", "transformation", "award", "title", "talent program"],
        "structure": ["文献-假设-验证结构", "实验-数据-分析结构", "问题-方法-结论结构"],
    },
    {
        "patterns": ["thesis", "dissertation", "毕业论文", "学位论文", "硕士论文", "博士论文", "开题报告", "中期检查", "盲审", "答辩"],
        "support": ["论文", "学位", "毕业", "硕士", "博士", "本科", "专科", "开题", "选题", "综述", "研究", "方法", "实验", "数据", "结果", "讨论", "结论", "摘要", "关键词", "引言", "背景", "意义", "目的", "问题", "假设", "理论", "模型", "框架", "设计", "实施", "分析", "写作", "修改", "润色", "查重", "降重", "格式", "排版", "引用", "参考文献", "附录", "致谢", "盲审", "评阅", "答辩", "PPT", "陈述", "提问", "回答", "通过", "优秀", "良好", "合格", "延期", "二次"],
        "semantic": ["thesis", "dissertation", "degree", "graduation", "master", "doctor", "bachelor", "proposal", "topic", "review", "research", "method", "experiment", "data", "result", "discussion", "conclusion", "abstract", "keyword", "introduction", "background", "significance", "purpose", "problem", "hypothesis", "theory", "model", "framework", "design", "implementation", "analysis", "writing", "revision", "polish", "plagiarism check", "format", "layout", "citation", "reference", "appendix", "acknowledgment", "blind review", "defense", "presentation", "statement", "question", "answer", "pass", "excellent", "good", "qualified", "postponement"],
        "structure": ["选题-研究-写作结构", "背景-方法-结果结构", "准备-答辩-修改结构"],
    },

    # ===== 实习与实训（1条） =====
    {
        "patterns": ["internship", "practical training", "实习", "实训", "见习", "顶岗实习", "毕业实习", "暑期实习", "寒假实习"],
        "support": ["实习", "实训", "见习", "顶岗", "毕业", "暑期", "寒假", "日常", "企业", "公司", "单位", "部门", "岗位", "职责", "任务", "项目", "导师", "带教", "师傅", "同事", "团队", "学习", "锻炼", "成长", "经验", "收获", "总结", "报告", "日志", "周记", "考核", "评价", "鉴定", "证明", "转正", "留用", "offer", "薪资", "补贴", "交通", "住宿", "保险", "安全", "纪律", "规范", "流程", "制度", "文化", "价值观", "职业", "素养", "技能", "证书", "资格"],
        "semantic": ["internship", "practical training", "probation", "graduation internship", "summer internship", "winter internship", "enterprise", "company", "department", "position", "responsibility", "task", "project", "mentor", "teaching", "colleague", "team", "learning", "exercise", "growth", "experience", "gain", "summary", "report", "log", "weekly", "assessment", "evaluation", "identification", "certificate", "regularization", "retention", "offer", "salary", "subsidy", "transportation", "accommodation", "insurance", "safety", "discipline", "norm", "process", "system", "culture", "value", "profession", "quality", "skill", "certificate", "qualification"],
        "structure": ["学习-实践-总结结构", "任务-执行-反馈结构", "观察-参与-独立结构"],
    },

    # ===== 社交与人脉（1条） =====
    {
        "patterns": ["networking", "social skills", "socializing", "社交", "人脉", "应酬", "饭局", "酒桌", "礼仪", "情商", "沟通", "表达", "演讲", "谈判", "说服"],
        "support": ["社交", "人际", "关系", "人脉", "圈子", "资源", "社交", "活动", "聚会", "饭局", "酒局", "应酬", "接待", "拜访", "送礼", "礼仪", "礼节", "礼貌", "仪态", "仪表", "着装", "举止", "言谈", "沟通", "交流", "对话", "倾听", "反馈", "表达", "陈述", "汇报", "演讲", "发言", "主持", "引导", "控场", "互动", "提问", "回答", "讨论", "协商", "谈判", "说服", "影响", "激励", "赞美", "批评", "拒绝", "道歉", "感谢", "情商", "情绪", "同理心", "换位思考", "信任", "尊重", "真诚", "幽默", "自信", "谦虚", "包容", "合作", "共赢"],
        "semantic": ["networking", "social", "relationship", "connection", "circle", "resource", "event", "party", "dinner", "drink", "entertainment", "reception", "visit", "gift", "etiquette", "manners", "politeness", "appearance", "dress", "behavior", "communication", "dialogue", "listening", "feedback", "expression", "presentation", "report", "speech", "speak", "host", "guide", "control", "interaction", "question", "answer", "discussion", "negotiation", "persuasion", "influence", "motivation", "praise", "criticism", "refusal", "apology", "gratitude", "EQ", "emotion", "empathy", "trust", "respect", "sincerity", "humor", "confidence", "humility", "inclusiveness", "cooperation", "win-win"],
        "structure": ["观察-倾听-回应结构", "准备-表达-跟进结构", "建立-维护-深化结构"],
    },


    # ===== 心理健康（2条） =====
    {
        "patterns": ["psychology", "mental health", "心理咨询", "心理治疗", "抑郁症", "焦虑症", "情绪管理", "正念", "冥想", "CBT"],
        "support": ["心理", "健康", "情绪", "情感", "认知", "行为", "思维", "信念", "态度", "人格", "性格", "气质", "能力", "智力", "动机", "需求", "冲突", "压力", "应激", "创伤", "PTSD", "抑郁", "焦虑", "强迫", "恐惧", "疑病", "双相", "精分", "障碍", "症", "咨询", "治疗", "辅导", "干预", "疏导", "倾听", "共情", "接纳", "支持", "陪伴", "成长", "改变", "觉察", "正念", "冥想", "放松", "呼吸", "身体扫描", "瑜伽", "CBT", "认知行为", "DBT", "ACT", "精神分析", "人本主义", "家庭治疗", "沙盘", "OH卡", "催眠", "叙事", "存在主义"],
        "semantic": ["psychology", "mental health", "emotion", "feeling", "cognition", "behavior", "thinking", "belief", "attitude", "personality", "character", "temperament", "ability", "intelligence", "motivation", "need", "conflict", "stress", "trauma", "PTSD", "depression", "anxiety", "OCD", "phobia", "hypochondria", "bipolar", "disorder", "counseling", "therapy", "guidance", "intervention", "venting", "listening", "empathy", "acceptance", "support", "companionship", "growth", "change", "awareness", "mindfulness", "meditation", "relaxation", "breathing", "body scan", "yoga", "CBT", "cognitive behavioral therapy", "DBT", "ACT", "psychoanalysis", "humanism", "family therapy", "sandplay", "OH card", "hypnosis", "narrative therapy", "existentialism"],
        "structure": ["评估-干预-跟进结构", "觉察-接纳-改变结构", "认知-情绪-行为结构"],
    },
    {
        "patterns": ["self-help", "personal growth", "自我提升", "个人成长", "自律", "习惯养成", "时间管理", "精力管理", "人生规划"],
        "support": ["自我", "提升", "成长", "发展", "进步", "改变", "突破", "蜕变", "进化", "自律", "自控", "意志力", "延迟满足", "习惯", "养成", "打破", "21天", "100天", "打卡", "坚持", "放弃", "重启", "时间管理", "四象限", "番茄钟", "GTD", "清单", "日历", "计划", "日程", "提醒", "精力管理", "体能", "情绪", "注意力", "意义感", "目标", "愿景", "使命", "价值观", "人生", "规划", "路径", "阶段", "里程碑", "复盘", "总结", "反思", "反馈", "调整", "优化", "迭代", "学习", "阅读", "写作", "思考", "实践", "输出", "分享", "导师", "教练", "社群", "同伴", "榜样", "偶像"],
        "semantic": ["self-help", "personal growth", "development", "progress", "change", "breakthrough", "transformation", "evolution", "self-discipline", "self-control", "willpower", "delayed gratification", "habit", "formation", "breaking", "check-in", "persistence", "restart", "time management", "quadrant", "pomodoro", "GTD", "to-do list", "calendar", "plan", "schedule", "reminder", "energy management", "physical energy", "emotional energy", "attention", "meaning", "goal", "vision", "mission", "value", "life planning", "path", "stage", "milestone", "review", "summary", "reflection", "feedback", "adjustment", "optimization", "iteration", "learning", "reading", "writing", "thinking", "practice", "output", "sharing", "mentor", "coach", "community", "peer", "role model", "idol"],
        "structure": ["目标-行动-复盘结构", "觉察-计划-执行结构", "输入-内化-输出结构"],
    },

    # ===== 医疗健康（2条） =====
    {
        "patterns": ["medicine", "clinical", "临床医学", "内科", "外科", "诊断", "治疗", "处方", "病历", "查房", "执业医师", "规培"],
        "support": ["医学", "临床", "基础", "预防", "康复", "内科", "外科", "妇科", "儿科", "急诊", "重症", "ICU", "肿瘤", "心血管", "神经", "消化", "呼吸", "内分泌", "免疫", "感染", "传染", "皮肤", "精神", "影像", "检验", "病理", "麻醉", "手术", "操作", "诊断", "鉴别", "症状", "体征", "病史", "查体", "辅助检查", "化验", "影像", "CT", "MRI", "X光", "B超", "处方", "用药", "剂量", "疗程", "不良反应", "禁忌", "病历", "病程", "记录", "查房", "交班", "会诊", "转诊", "出院", "随访", "执业医师", "规培", "进修", "轮转", "科室", "主任", "主治", "住院", "实习医生", "护士", "护理", "医嘱"],
        "semantic": ["medicine", "clinical", "basic medicine", "preventive", "rehabilitation", "internal medicine", "surgery", "gynecology", "pediatrics", "emergency", "critical care", "ICU", "oncology", "cardiovascular", "neurology", "gastroenterology", "respiratory", "endocrinology", "immunology", "infectious", "dermatology", "psychiatry", "radiology", "laboratory", "pathology", "anesthesiology", "surgery", "procedure", "diagnosis", "differential diagnosis", "symptom", "sign", "history", "physical exam", "ancillary test", "lab test", "imaging", "CT", "MRI", "X-ray", "ultrasound", "prescription", "medication", "dosage", "course", "side effect", "contraindication", "medical record", "ward round", "handover", "consultation", "referral", "discharge", "follow-up", "licensed physician", "residency", "training", "rotation", "department", "chief", "attending", "resident", "intern", "nurse", "nursing", "doctor's order"],
        "structure": ["问诊-查体-诊断结构", "诊断-治疗-随访结构", "评估-干预-评估结构"],
    },
    {
        "patterns": ["nursing", "public health", "护理", "公卫", "预防医学", "流行病学", "健康管理", "营养师", "康复师"],
        "support": ["护理", "护士", "照护", "患者", "病情", "生命体征", "体温", "脉搏", "呼吸", "血压", "血糖", "出入量", "给药", "注射", "输液", "换药", "导管", "引流", "压疮", "跌倒", "坠床", "感染", "控制", "消毒", "隔离", "手卫生", "公卫", "预防", "流行病", "统计", "调查", "监测", "预警", "应急", "预案", "疫苗", "接种", "免疫", "筛查", "体检", "健康", "管理", "档案", "评估", "干预", "随访", "营养", "膳食", "配餐", "康复", "理疗", "运动", "作业", "言语", "心理", "社会", "工作", "个案", "小组", "社区"],
        "semantic": ["nursing", "nurse", "care", "patient", "condition", "vital signs", "temperature", "pulse", "respiration", "blood pressure", "blood glucose", "intake and output", "medication", "injection", "infusion", "dressing change", "catheter", "drainage", "pressure sore", "fall", "infection", "control", "disinfection", "isolation", "hand hygiene", "public health", "prevention", "epidemiology", "statistics", "survey", "surveillance", "early warning", "emergency", "plan", "vaccine", "vaccination", "immunity", "screening", "physical exam", "health", "management", "record", "assessment", "intervention", "follow-up", "nutrition", "diet", "meal planning", "rehabilitation", "physical therapy", "exercise", "occupational therapy", "speech therapy", "psychology", "social work", "case", "group", "community"],
        "structure": ["评估-计划-实施结构", "预防-监测-干预结构", "问题-目标-措施结构"],
    },

    # ===== 农林牧渔（2条） =====
    {
        "patterns": ["agriculture", "farming", "农业", "种植", "作物", "农机", "化肥", "农药", "育种", "栽培", "土壤", "灌溉"],
        "support": ["农业", "农村", "农民", "三农", "种植", "养殖", "畜牧", "兽医", "水产", "渔业", "林业", "园林", "园艺", "作物", "粮食", "水稻", "小麦", "玉米", "大豆", "棉花", "油菜", "甘蔗", "蔬菜", "水果", "茶叶", "中药材", "育种", "选种", "播种", "育苗", "移栽", "定植", "栽培", "管理", "施肥", "化肥", "有机肥", "农药", "病虫害", "防治", "除草", "灌溉", "排水", "土壤", "耕地", "轮作", "间作", "套作", "农机", "拖拉机", "收割机", "无人机", "遥感", "智慧农业", "温室", "大棚", "设施农业", "生态农业", "有机农业", "绿色农业", "可持续"],
        "semantic": ["agriculture", "countryside", "farmer", "rural development", "planting", "breeding", "animal husbandry", "veterinary", "aquaculture", "fishery", "forestry", "garden", "horticulture", "crop", "grain", "rice", "wheat", "corn", "soybean", "cotton", "rapeseed", "sugarcane", "vegetable", "fruit", "tea", "Chinese herbal medicine", "seed breeding", "selection", "sowing", "seedling", "transplanting", "cultivation", "management", "fertilization", "chemical fertilizer", "organic fertilizer", "pesticide", "pest", "disease", "control", "weeding", "irrigation", "drainage", "soil", "tillage", "rotation", "intercropping", "relay cropping", "agricultural machinery", "tractor", "harvester", "drone", "remote sensing", "smart agriculture", "greenhouse", "facility agriculture", "eco-agriculture", "organic farming", "green agriculture", "sustainable"],
        "structure": ["选种-播种-管理结构", "环境-投入-产出结构", "监测-诊断-干预结构"],
    },
    {
        "patterns": ["animal husbandry", "veterinary", "畜牧", "兽医", "养殖", "饲料", "兽药", "疫病", "屠宰", "检疫"],
        "support": ["畜牧", "养殖", "饲养", "饲料", "营养", "配方", "预混料", "全价料", "浓缩料", "牧草", "青贮", "放牧", "圈养", "笼养", "散养", "家畜", "猪", "牛", "羊", "马", "驴", "兔", "家禽", "鸡", "鸭", "鹅", "鸽", "特种养殖", "蜂", "蚕", "鹿", "貂", "狐狸", "水产", "鱼", "虾", "蟹", "贝", "参", "藻", "池塘", "网箱", "工厂化", "循环水", "兽医", "动物", "疾病", "诊断", "治疗", "免疫", "疫苗", "驱虫", "消毒", "无害化", "屠宰", "加工", "检疫", "检验", "冷链", "溯源", "品种", "繁育", "杂交", "改良", "系谱", "性能", "测定"],
        "semantic": ["animal husbandry", "breeding", "feeding", "feed", "nutrition", "formula", "premix", "complete feed", "concentrate", "forage", "silage", "grazing", "pen raising", "cage raising", "free range", "livestock", "pig", "cattle", "sheep", "horse", "donkey", "rabbit", "poultry", "chicken", "duck", "goose", "pigeon", "special breeding", "bee", "silkworm", "deer", "mink", "fox", "aquaculture", "fish", "shrimp", "crab", "shellfish", "sea cucumber", "algae", "pond", "cage", "industrial", "recirculating aquaculture", "veterinary", "animal", "disease", "diagnosis", "treatment", "immunity", "vaccine", "deworming", "disinfection", "harmless treatment", "slaughter", "processing", "quarantine", "inspection", "cold chain", "traceability", "breed", "reproduction", "crossbreeding", "improvement", "pedigree", "performance", "testing"],
        "structure": ["饲养-管理-防疫结构", "繁育-生长-出栏结构", "环境-营养-健康结构"],
    },

    # ===== 食品与纺织（2条） =====
    {
        "patterns": ["food science", "food engineering", "食品科学", "食品加工", "食品安全", "营养学", "烘焙", "酿酒", "发酵"],
        "support": ["食品", "食物", "食材", "原料", "加工", "生产", "制造", "工艺", "配方", "配方", "研发", "创新", "产品", "开发", "感官", "评价", "风味", "口感", "色泽", "香气", "质地", "保鲜", "保质", "贮藏", "运输", "冷链", "包装", "标签", "营养", "成分", "热量", "蛋白质", "脂肪", "碳水化合物", "维生素", "矿物质", "膳食纤维", "添加剂", "防腐剂", "色素", "香精", "安全", "卫生", "标准", "法规", "检测", "检验", "认证", "HACCP", "ISO", "有机", "绿色", "无公害", "烘焙", "面包", "蛋糕", "甜点", "巧克力", "酿酒", "啤酒", "葡萄酒", "白酒", "发酵", "酸奶", "酱油", "醋", "调味品"],
        "semantic": ["food science", "food", "ingredient", "raw material", "processing", "production", "manufacturing", "technology", "recipe", "formulation", "R&D", "innovation", "product", "development", "sensory", "evaluation", "flavor", "taste", "color", "aroma", "texture", "freshness", "shelf life", "storage", "transportation", "cold chain", "packaging", "label", "nutrition", "component", "calorie", "protein", "fat", "carbohydrate", "vitamin", "mineral", "dietary fiber", "additive", "preservative", "colorant", "flavoring", "safety", "hygiene", "standard", "regulation", "testing", "inspection", "certification", "HACCP", "ISO", "organic", "green", "pollution-free", "baking", "bread", "cake", "dessert", "chocolate", "brewing", "beer", "wine", "liquor", "fermentation", "yogurt", "soy sauce", "vinegar", "seasoning"],
        "structure": ["原料-加工-成品结构", "研发-测试-量产结构", "检测-标准-认证结构"],
    },
    {
        "patterns": ["textile", "fashion design", "纺织", "服装", "面料", "染色", "印花", "服装设计", "打版", "裁剪", "缝纫"],
        "support": ["纺织", "纤维", "纱线", "面料", "织物", "针织", "梭织", "无纺", "牛仔", "丝绸", "棉", "麻", "毛", "化纤", "功能", "智能", "染色", "印花", "整理", "后整理", "前处理", "退浆", "煮练", "漂白", "丝光", "定型", "预缩", "抗皱", "防水", "透气", "保暖", "抗菌", "防紫外", "服装", "设计", "款式", "版型", "结构", "工艺", "打版", "制版", "立裁", "平裁", "裁剪", "排料", "缝纫", "缝制", "锁边", "整烫", "质检", "面料", "辅料", "拉链", "纽扣", "商标", "吊牌", "包装", "陈列", "时尚", "潮流", "品牌", "走秀", "T台", "定制", "高定", "成衣", "快时尚"],
        "semantic": ["textile", "fiber", "yarn", "fabric", "knitting", "weaving", "non-woven", "denim", "silk", "cotton", "linen", "wool", "chemical fiber", "functional", "smart", "dyeing", "printing", "finishing", "pretreatment", "desizing", "scouring", "bleaching", "mercerization", "setting", "pre-shrinking", "anti-wrinkle", "waterproof", "breathable", "warm", "antibacterial", "UV protection", "clothing", "design", "style", "pattern", "structure", "technology", "pattern making", "draping", "flat cutting", "cutting", "marker making", "sewing", "stitching", "overlocking", "pressing", "quality inspection", "accessory", "zipper", "button", "label", "hang tag", "packaging", "display", "fashion", "trend", "brand", "runway", "catwalk", "customization", "haute couture", "ready-to-wear", "fast fashion"],
        "structure": ["纤维-纱线-面料结构", "设计-打版-制作结构", "检测-整理-包装结构"],
    },

    # ===== 考古与文博（1条） =====
    {
        "patterns": ["archaeology", "cultural heritage", "考古", "文物", "博物馆", "文博", "发掘", "鉴定", "修复", "保护"],
        "support": ["考古", "文物", "博物", " Heritage", "遗址", "遗迹", "墓葬", "城址", "窑址", "窖藏", "发掘", "勘探", "调查", "测绘", "记录", "绘图", "摄影", "标本", "遗物", "遗迹", "地层", "年代", "类型", "分期", "分区", "文化", "因素", "交流", "传播", "演变", "鉴定", "真伪", "年代", "材质", "工艺", "风格", "修复", "保护", "加固", "清洗", "拼接", "补配", "着色", "封存", "环境", "展陈", "说明", "讲解", "教育", "传播", "非遗", "传承", "传承人", "技艺", "民俗", "节庆", "仪式"],
        "semantic": ["archaeology", "cultural relic", "museum", "heritage", "site", "ruin", "tomb", "city site", "kiln site", "hoard", "excavation", "exploration", "survey", "mapping", "recording", "drawing", "photography", "specimen", "remains", "stratum", "dating", "typology", "periodization", "region", "culture", "factor", "exchange", "diffusion", "evolution", "authentication", "authenticity", "date", "material", "craftsmanship", "style", "restoration", "conservation", "reinforcement", "cleaning", "joining", "infilling", "coloring", "sealing", "environment", "exhibition", "caption", "interpretation", "education", "communication", "intangible heritage", "inheritance", "inheritor", "skill", "folklore", "festival", "ritual"],
        "structure": ["发现-发掘-研究结构", "鉴定-修复-保护结构", "收集-展陈-教育结构"],
    },

    # ===== 图书情报（1条） =====
    {
        "patterns": ["library science", "information science", "图书馆学", "情报学", "档案", "编目", "分类", "检索", "数字人文"],
        "support": ["图书馆", "情报", "档案", "文献", "信息", "资源", "采集", "采购", "编目", "分类", "标引", "索引", "目录", "馆藏", "借阅", "流通", "参考", "咨询", "检索", "查新", "引证", "分析", "计量", "评价", "数据库", "数字", "电子", "资源", "开放获取", "OA", "知识产权", "版权", "许可", "机构库", "知识库", "学科", "服务", "空间", "阅读", "推广", "活动", "展览", "讲座", "培训", "素养", "教育", "数字人文", "数据", "挖掘", "可视化", "GIS", "文本", "分析", "语料库"],
        "semantic": ["library science", "information science", "archive", "document", "information", "resource", "acquisition", "cataloging", "classification", "indexing", "index", "catalog", "collection", "lending", "circulation", "reference", "consultation", "retrieval", "novelty search", "citation", "analysis", "bibliometrics", "evaluation", "database", "digital", "electronic resource", "open access", "OA", "intellectual property", "copyright", "license", "institutional repository", "knowledge base", "subject service", "space", "reading", "promotion", "activity", "exhibition", "lecture", "training", "literacy", "education", "digital humanities", "data mining", "visualization", "GIS", "text analysis", "corpus"],
        "structure": ["采集-组织-服务结构", "检索-分析-评价结构", "保存-传播-利用结构"],
    },

    # ===== 旅游与酒店（1条） =====
    {
        "patterns": ["tourism", "hospitality", "旅游管理", "酒店管理", "会展", "导游", "景区", "OTA", "民宿运营"],
        "support": ["旅游", "旅行", "观光", "游览", "休闲", "度假", "商务", "会议", "会展", "活动", "酒店", "住宿", "餐饮", "交通", "航空", "铁路", "公路", "景区", "景点", "门票", "线路", "行程", "攻略", "导游", "领队", "翻译", "接待", "服务", "前台", "客房", "餐饮", "宴会", "康乐", "SPA", "会员", "OTA", "携程", "飞猪", "美团", "Booking", "Airbnb", "民宿", "客栈", "青旅", "运营", "推广", "营销", "品牌", "收益", "管理", "服务", "质量", "满意度", "投诉", "处理", "安全", "应急", "预案"],
        "semantic": ["tourism", "travel", "sightseeing", "tour", "leisure", "vacation", "business travel", "conference", "exhibition", "event", "hotel", "accommodation", "catering", "transportation", "aviation", "railway", "highway", "scenic area", "attraction", "ticket", "route", "itinerary", "guide", "tour leader", "translation", "reception", "service", "front desk", "housekeeping", "dining", "banquet", "recreation", "SPA", "member", "OTA", "Ctrip", "Fliggy", "Meituan", "Booking", "Airbnb", "homestay", "inn", "hostel", "operation", "promotion", "marketing", "brand", "revenue", "management", "quality", "satisfaction", "complaint", "handling", "safety", "emergency", "plan"],
        "structure": ["资源-产品-市场结构", "接待-服务-反馈结构", "策划-执行-评估结构"],
    },

    # ===== 物流与供应链（1条） =====
    {
        "patterns": ["logistics", "supply chain", "物流", "供应链", "仓储", "运输", "配送", "采购", "库存", "ERP", "WMS", "TMS"],
        "support": ["物流", "供应", "链", "采购", "生产", "制造", "仓储", "仓库", "库存", "分拣", "包装", "装卸", "搬运", "运输", "配送", "快递", "快运", "冷链", "跨境", "国际", "贸易", "海关", "报关", "清关", "单证", "承运", "第三方", "第四方", "园区", "港口", "机场", "公路", "铁路", "水运", "多式联运", "集装", "托盘", "标准化", "信息化", "数字化", "智能", "自动", "机器人", "AGV", "无人机", "ERP", "WMS", "TMS", "OMS", "BOM", "MRP", "JIT", "精益", "敏捷", "柔性", "韧性", "风险", "成本", "效率", "KPI", "可视化", "追踪", "溯源"],
        "semantic": ["logistics", "supply chain", "procurement", "production", "manufacturing", "warehousing", "warehouse", "inventory", "sorting", "packaging", "loading", "handling", "transportation", "distribution", "express", "freight", "cold chain", "cross-border", "international trade", "customs", "declaration", "clearance", "document", "carrier", "3PL", "4PL", "park", "port", "airport", "highway", "railway", "waterway", "multimodal transport", "container", "pallet", "standardization", "informatization", "digitalization", "intelligent", "automation", "robot", "AGV", "drone", "ERP", "WMS", "TMS", "OMS", "BOM", "MRP", "JIT", "lean", "agile", "flexible", "resilient", "risk", "cost", "efficiency", "KPI", "visibility", "tracking", "traceability"],
        "structure": ["采购-生产-配送结构", "计划-执行-监控结构", "入库-存储-出库结构"],
    },

    # ===== 国际贸易与商务（1条） =====
    {
        "patterns": ["international trade", "business", "国际贸易", "外贸", "进出口", "报关", "跨境电商", "单证", "信用证", "FOB", "CIF"],
        "support": ["贸易", "国际", "全球", "外贸", "进出口", "出口", "进口", "转口", "加工", "保税", "自贸", "关税", "壁垒", "协定", "WTO", "RCEP", "一带一路", "跨境", "电商", "平台", "亚马逊", "eBay", "速卖通", "Wish", "Shopee", "Lazada", "独立站", "DTC", "海关", "报关", "清关", "商检", "原产地", "配额", "许可证", "外汇", "结算", "信用证", "L/C", "T/T", "D/P", "D/A", "O/A", "保理", "福费廷", "保险", "海运", "空运", "陆运", "提单", "B/L", "舱单", "装箱单", "发票", "合同", "形式发票", "报价", "询盘", "发盘", "还盘", "接受", "谈判", "仲裁", "纠纷", "合规", "反倾销", "反补贴", "337"],
        "semantic": ["international trade", "global trade", "foreign trade", "import", "export", "re-export", "processing", "bonded", "free trade", "tariff", "barrier", "agreement", "WTO", "RCEP", "Belt and Road", "cross-border", "e-commerce", "platform", "Amazon", "eBay", "AliExpress", "Wish", "Shopee", "Lazada", "independent site", "DTC", "customs", "declaration", "clearance", "commodity inspection", "origin", "quota", "license", "foreign exchange", "settlement", "L/C", "T/T", "D/P", "D/A", "O/A", "factoring", "forfaiting", "insurance", "ocean freight", "air freight", "land transport", "B/L", "manifest", "packing list", "invoice", "contract", "proforma invoice", "inquiry", "offer", "counter-offer", "acceptance", "negotiation", "arbitration", "dispute", "compliance", "anti-dumping", "countervailing", "Section 337"],
        "structure": ["询盘-报价-成交结构", "生产-物流-结算结构", "谈判-合同-履行结构"],
    },

    # ===== 房地产与建筑运营（1条） =====
    {
        "patterns": ["real estate", "property management", "房地产", "物业管理", "工程造价", "估价", "经纪", "营销", "开发", "运营"],
        "support": ["房地产", "地产", "房产", "住宅", "商业", "办公", "工业", "土地", "出让", "招拍挂", "一级", "二级", "开发", "投资", "融资", "代建", "EPC", "设计", "施工", "监理", "验收", "交付", "物业", "管理", "服务", "维修", "养护", "保洁", "绿化", "安保", "消防", "停车", "收费", "业主", "业委会", "租户", "租金", "租约", "空置", "去化", "存量", "增量", "经纪", "中介", "代理", "销售", "渠道", "分销", "策划", "推广", "广告", "活动", "品牌", "估价", "评估", "抵押", "按揭", "贷款", "公积金", "利率", "政策", "调控", "限购", "限贷", "限售", "房产税", "土增税", "契税", "营改增"],
        "semantic": ["real estate", "property", "residential", "commercial", "office", "industrial", "land", "conveyance", "bidding", "primary market", "secondary market", "development", "investment", "financing", "construction management", "EPC", "design", "construction", "supervision", "acceptance", "delivery", "property management", "service", "maintenance", "cleaning", "landscaping", "security", "firefighting", "parking", "fee", "owner", "committee", "tenant", "rent", "lease", "vacancy", "absorption", "stock", "increment", "brokerage", "agent", "sales", "channel", "distribution", "planning", "promotion", "advertising", "event", "brand", "appraisal", "valuation", "mortgage", "housing loan", "provident fund", "interest rate", "policy", "regulation", "purchase restriction", "loan restriction", "sales restriction", "property tax", "land appreciation tax", "deed tax", "VAT reform"],
        "structure": ["拿地-开发-销售结构", "建设-验收-交付结构", "服务-运营-增值结构"],
    },

    # ===== 安全与应急（1条） =====
    {
        "patterns": ["safety engineering", "fire protection", "安全工程", "消防", "应急管理", "安全生产", "职业健康", "EHS"],
        "support": ["安全", "健康", "环境", "EHS", "HSE", "安全生产", "职业", "卫生", "消防", "防火", "灭火", "逃生", "疏散", "应急", "预案", "演练", "响应", "救援", "抢救", "减灾", "防灾", "抗震", "防洪", "防汛", "抗旱", "防风", "防雷", "防台", "地质灾害", "滑坡", "泥石流", "崩塌", "地震", "火山", "危险", "源", "风险", "识别", "评估", "控制", "消除", "替代", "隔离", "通风", "防护", "PPE", "头盔", "眼镜", "手套", "口罩", "防护服", "安全带", "监测", "检测", "报警", "联锁", "DCS", "SIS", "PLC", "事故", "调查", "分析", "报告", "处理", "追责", "整改", " closure"],
        "semantic": ["safety", "health", "environment", "EHS", "HSE", "work safety", "occupational health", "fire protection", "firefighting", "escape", "evacuation", "emergency", "plan", "drill", "response", "rescue", "disaster reduction", "earthquake resistance", "flood control", "drought resistance", "wind protection", "lightning protection", "typhoon protection", "geological hazard", "landslide", "debris flow", "collapse", "earthquake", "volcano", "hazard", "risk", "identification", "assessment", "control", "elimination", "substitution", "isolation", "ventilation", "protection", "PPE", "helmet", "goggles", "gloves", "mask", "protective clothing", "safety belt", "monitoring", "detection", "alarm", "interlock", "DCS", "SIS", "PLC", "accident", "investigation", "analysis", "report", "handling", "accountability", "rectification", "closure"],
        "structure": ["识别-评估-控制结构", "预防-准备-响应结构", "监测-预警-处置结构"],
    },

    # ===== 地质与矿业（1条） =====
    {
        "patterns": ["geology", "mining", "地质", "矿业", "采矿", "选矿", "冶炼", "勘探", "储量", "矿山", "安全"],
        "support": ["地质", "岩石", "矿物", "矿石", "矿床", "成矿", "找矿", "勘探", "钻探", "坑探", "槽探", "物探", "化探", "遥感", "测绘", "制图", "样品", "测试", "分析", "储量", "资源", "评估", "矿山", "开采", "采矿", "露天", "地下", "井工", "选矿", "破碎", "磨矿", "浮选", "磁选", "重选", "冶炼", "焙烧", "浸出", "电解", "精炼", "尾矿", "废石", "矸石", "复垦", "生态", "恢复", "安全", "通风", "排水", "支护", "爆破", "运输", "提升", "监测", "瓦斯", "粉尘", "地压", "水害", "火灾"],
        "semantic": ["geology", "rock", "mineral", "ore", "deposit", "mineralization", "prospecting", "exploration", "drilling", "trenching", "geophysical", "geochemical", "remote sensing", "surveying", "mapping", "sample", "testing", "analysis", "reserve", "resource", "assessment", "mine", "mining", "open-pit", "underground", "mineral processing", "crushing", "grinding", "flotation", "magnetic separation", "gravity separation", "smelting", "roasting", "leaching", "electrolysis", "refining", "tailings", "waste rock", "gangue", "reclamation", "ecological restoration", "safety", "ventilation", "drainage", "support", "blasting", "transportation", "hoisting", "monitoring", "gas", "dust", "ground pressure", "water hazard", "fire"],
        "structure": ["勘探-评估-开发结构", "开采-选矿-冶炼结构", "安全-环保-复垦结构"],
    },

    # ===== 海洋与气象（2条） =====
    {
        "patterns": ["oceanography", "marine science", "海洋", "海洋学", "航海", "造船", "水产", "港口", "海岸", "海岛"],
        "support": ["海洋", "海水", "海流", "潮汐", "波浪", "风暴潮", " tsunami", "海平面", "上升", "温度", "盐度", "密度", "声速", "光学", "遥感", "卫星", "浮标", "潜标", "Argo", "CTD", "ADCP", "沉积", "底质", "生物", "生态", "渔业", "养殖", "捕捞", "加工", "船舶", "造船", "设计", "建造", "检验", "登记", "航行", "导航", "通讯", "港口", "码头", "泊位", "航道", "疏浚", "防波堤", "海岸", "防护", "围填海", "海岛", "开发", "保护", "治理", "维权", "执法"],
        "semantic": ["oceanography", "seawater", "current", "tide", "wave", "storm surge", "tsunami", "sea level rise", "temperature", "salinity", "density", "sound speed", "optics", "remote sensing", "satellite", "buoy", "subsurface mooring", "Argo", "CTD", "ADCP", "sediment", "substrate", "biology", "ecology", "fishery", "aquaculture", "fishing", "processing", "ship", "shipbuilding", "design", "construction", "inspection", "registration", "navigation", "communication", "port", "wharf", "berth", "channel", "dredging", "breakwater", "coastal protection", "reclamation", "island", "development", "protection", "governance", "rights protection", "law enforcement"],
        "structure": ["观测-分析-预测结构", "勘探-开发-保护结构", "设计-建造-运维结构"],
    },
    {
        "patterns": ["meteorology", "atmospheric science", "气象", "大气科学", "天气预报", "气候", "遥感", "卫星", "防灾"],
        "support": ["气象", "天气", "气候", "大气", "温度", "气压", "湿度", "风", "降水", "云", "雾", "霜", "雪", "冰雹", "雷电", "台风", "飓风", "龙卷风", "暴雨", "洪涝", "干旱", "高温", "寒潮", "沙尘", "雾霾", "臭氧", "温室", "效应", "变化", "变暖", "碳", "中和", "减排", "适应", "脆弱", "评估", "预报", "预测", "预警", "监测", "雷达", "卫星", "遥感", "探空", "站", "自动", "模式", "数值", "ECMWF", "GFS", "WRF", "GRAPES", "服务", "决策", "公众", "专业", "农业", "交通", "能源", "海洋", "健康", "旅游", "赛事", "人工", "影响", "增雨", "消雹", "防雷"],
        "semantic": ["meteorology", "weather", "climate", "atmosphere", "temperature", "pressure", "humidity", "wind", "precipitation", "cloud", "fog", "frost", "snow", "hail", "lightning", "typhoon", "hurricane", "tornado", "heavy rain", "flood", "drought", "heat wave", "cold wave", "sandstorm", "haze", "ozone", "greenhouse effect", "climate change", "global warming", "carbon neutrality", "emission reduction", "adaptation", "vulnerability", "assessment", "forecast", "prediction", "early warning", "monitoring", "radar", "satellite", "remote sensing", "radiosonde", "automatic station", "model", "numerical", "ECMWF", "GFS", "WRF", "GRAPES", "service", "decision-making", "public", "professional", "agriculture", "transportation", "energy", "ocean", "health", "tourism", "event", "weather modification", "rain enhancement", "hail suppression", "lightning protection"],
        "structure": ["观测-模拟-预报结构", "监测-预警-服务结构", "评估-适应-减缓结构"],
    },

    # ===== 军事与国防（1条） =====
    {
        "patterns": ["military", "national defense", "军事", "国防", "战略", "战术", "武器", "装备", "信息化", "联合作战"],
        "support": ["军事", "国防", "军队", "武装", "力量", "陆军", "海军", "空军", "火箭军", "战略", "支援", "部队", "联勤", "预备役", "民兵", "征兵", "服役", "退役", "军官", "士官", "士兵", "军衔", "等级", "战略", "战术", "战役", "战斗", "作战", "指挥", "控制", "通信", "情报", "侦察", "监视", "电子", "网络", "太空", "导弹", "核", "常规", "武器", "装备", "平台", "系统", "弹药", "后勤", "保障", "补给", "运输", "医疗", "工程", "伪装", "防护", "训练", "演习", "演练", "想定", "裁判", "评估", "信息化", "数字化", "智能化", "无人", "人工智能", "大数据", "区块链", "量子"],
        "semantic": ["military", "national defense", "armed forces", "army", "navy", "air force", "rocket force", "strategic support force", "joint logistics", "reserve", "militia", "conscription", "service", "retirement", "officer", "non-commissioned officer", "soldier", "rank", "strategy", "tactics", "campaign", "combat", "operation", "command", "control", "communication", "intelligence", "reconnaissance", "surveillance", "electronic warfare", "cyber", "space", "missile", "nuclear", "conventional", "weapon", "equipment", "platform", "system", "ammunition", "logistics", "support", "supply", "transportation", "medical", "engineering", "camouflage", "protection", "training", "exercise", "drill", "scenario", "umpire", "assessment", "informatization", "digitalization", "intelligentization", "unmanned", "AI", "big data", "blockchain", "quantum"],
        "structure": ["侦察-决策-打击结构", "训练-演习-评估结构", "研发-列装-保障结构"],
    },

    # ===== 宗教与哲学修行（1条） =====
    {
        "patterns": ["religion", "philosophy", "宗教", "哲学", "修行", "禅修", "道家", "佛家", "瑜伽", "灵性", "神学"],
        "support": ["宗教", "信仰", "神学", "圣经", "古兰经", "佛经", "道藏", "儒典", "教堂", "寺庙", "清真寺", "道观", "仪式", "礼拜", "祈祷", "诵经", "弥撒", "朝觐", "法会", "打坐", "禅修", "冥想", "内观", "正念", "瑜伽", "呼吸", "脉轮", "能量", "气场", "灵性", "觉醒", "开悟", "涅槃", "解脱", "轮回", "因果", "业力", " karma", "道", "德", "无为", "自然", "阴阳", "五行", "八卦", "风水", "命理", "占卜", "塔罗", "占星", "哲学", "形而上学", "认识论", "伦理学", "美学", "逻辑", "存在", "本质", "真理", "知识", "语言", "心灵", "意识", "自由", "正义", "善", "美"],
        "semantic": ["religion", "faith", "theology", "Bible", "Quran", "Buddhist scripture", "Taoist canon", "Confucian classic", "church", "temple", "mosque", "Taoist temple", "ritual", "worship", "prayer", "chanting", "mass", "pilgrimage", "Dharma assembly", "meditation", "zen", "vipassana", "mindfulness", "yoga", "breath", "chakra", "energy", "aura", "spirituality", "awakening", "enlightenment", "nirvana", "liberation", "reincarnation", "cause and effect", "karma", "Tao", "virtue", "wu wei", "naturalness", "yin-yang", "five elements", "bagua", "feng shui", "fortune telling", "divination", "tarot", "astrology", "philosophy", "metaphysics", "epistemology", "ethics", "aesthetics", "logic", "existence", "essence", "truth", "knowledge", "language", "mind", "consciousness", "freedom", "justice", "good", "beauty"],
        "structure": ["学习-实践-体悟结构", "质疑-反思-整合结构", "修行-觉察-转化结构"],
    },

    # ===== 公益与社工（1条） =====
    {
        "patterns": ["charity", "social work", "公益", "慈善", "社工", "志愿服务", "NGO", "非营利", "社区服务", "帮扶"],
        "support": ["公益", "慈善", "志愿", "服务", "奉献", "爱心", "互助", "帮扶", "救助", "救援", "捐赠", "筹款", "募捐", "义卖", "拍卖", "基金", "基金会", "NGO", "NPO", "社会组织", "社会团体", "民办非企业", "社工", "社会", "工作", "个案", "小组", "社区", "行政", "督导", "评估", "研究", "倡导", "政策", "儿童", "青少年", "老年", "妇女", "家庭", "残障", "贫困", "流浪", "禁毒", "矫正", "学校", "医务", "企业", "灾害", "应急", "环保", "动物", "保护", "文化传承", "教育", "公平", "正义", "包容", "多元", "平等", "参与", "赋能", "增权", "可持续"],
        "semantic": ["charity", "philanthropy", "volunteer", "service", "dedication", "love", "mutual help", "assistance", "rescue", "relief", "donation", "fundraising", "bazaar", "auction", "foundation", "NGO", "NPO", "social organization", "social work", "case", "group", "community", "administration", "supervision", "evaluation", "research", "advocacy", "policy", "child", "youth", "elderly", "women", "family", "disability", "poverty", "vagrant", "drug control", "correction", "school", "medical", "enterprise", "disaster", "emergency", "environment", "animal protection", "cultural heritage", "education", "equity", "justice", "inclusion", "diversity", "equality", "participation", "empowerment", "sustainability"],
        "structure": ["需求-资源-服务结构", "评估-干预-跟进结构", "倡导-政策-改变结构"],
    },

    # ===== 殡葬与礼仪（1条） =====
    {
        "patterns": ["funeral", "mortuary", "殡葬", "殡仪", "墓地", "火化", "安葬", "临终关怀", "悲伤辅导"],
        "support": ["殡葬", "殡仪", "丧葬", "葬礼", "仪式", "守灵", "告别", "追悼", "祭奠", "祭祀", "扫墓", "骨灰", "骨灰盒", "骨灰堂", "公墓", "陵园", "墓地", "墓穴", "碑", "墓志铭", "火化", "焚化", "遗体", "接运", "整容", "化妆", "防腐", "冷藏", "寿衣", "棺木", "花圈", "挽联", "讣告", "报丧", "吊唁", "慰问", "抚恤", "临终", "关怀", "安宁", "疗护", "舒缓", "疼痛", "控制", "心理", "支持", "悲伤", "辅导", "哀伤", "疗愈", "接受", "放下", "继续", "遗嘱", "遗产", "继承", "公证", "风水", "择日", "宗教", "超度", "法事"],
        "semantic": ["funeral", "mortuary", "burial", "ceremony", "wake", "farewell", "memorial", "worship", "grave sweeping", "ashes", "urn", "columbarium", "cemetery", "tomb", "grave", "stele", "epitaph", "cremation", "incineration", "remains", "transport", "embalming", "makeup", "preservation", "refrigeration", "burial clothing", "coffin", "wreath", "elegiac couplet", "obituary", "condolence", "sympathy", "pension", "hospice", "palliative care", "pain management", "psychological support", "grief counseling", "bereavement", "healing", "acceptance", "letting go", "moving on", "will", "estate", "inheritance", "notarization", "feng shui", "date selection", "religion", "soul deliverance", "ritual"],
        "structure": ["接运-服务-安葬结构", "临终-关怀-哀伤结构", "仪式-纪念-传承结构"],
    },

    # ===== 家庭与生活（3条） =====
    {
        "patterns": ["parenting", "family education", "家庭教育", "育儿", "早教", "亲子", "蒙台梭利", "正面管教"],
        "support": ["家庭", "教育", "育儿", "养育", "抚养", "培育", "早教", "启蒙", "发展", "成长", "儿童", "幼儿", "婴儿", "青少年", "青春期", "心理", "健康", "安全", "营养", "睡眠", "运动", "游戏", "玩耍", "学习", "习惯", "规则", "边界", "纪律", "奖惩", "沟通", "倾听", "理解", "尊重", "信任", "陪伴", "依恋", "安全感", "蒙台梭利", "瑞吉欧", "华德福", "正面管教", "PET", "游戏力", "非暴力沟通", "父母", "角色", "榜样", "情绪", "管理", "压力", "焦虑", "挫败", "耐心", "接纳", "鼓励", "赞美", "批评", "惩罚", "自然", "后果", "合作", "解决", "冲突", "手足", "二胎", "三胎", "隔代", "祖辈", "保姆", "家园", "学校", "社区"],
        "semantic": ["parenting", "family education", "child rearing", "early education", "enlightenment", "development", "growth", "child", "toddler", "baby", "adolescent", "puberty", "psychology", "health", "safety", "nutrition", "sleep", "exercise", "play", "learning", "habit", "rule", "boundary", "discipline", "reward and punishment", "communication", "listening", "understanding", "respect", "trust", "companionship", "attachment", "security", "Montessori", "Reggio Emilia", "Waldorf", "positive discipline", "PET", "playful parenting", "nonviolent communication", "parent", "role model", "emotion management", "stress", "anxiety", "frustration", "patience", "acceptance", "encouragement", "praise", "criticism", "punishment", "natural consequence", "cooperation", "conflict resolution", "sibling", "grandparent", "nanny", "school", "community"],
        "structure": ["观察-理解-回应结构", "规则-沟通-合作结构", "陪伴-引导-放手结构"],
    },
    {
        "patterns": ["pet", "animal care", "宠物", "养猫", "养狗", " aquarium", "爬宠", "异宠", "宠物训练", "宠物医疗"],
        "support": ["宠物", "动物", "饲养", "照顾", "养护", "训练", "医疗", "健康", "营养", "饮食", "喂食", "饮水", "疫苗", "驱虫", "体检", "绝育", "疾病", "症状", "诊断", "治疗", "护理", "康复", "美容", "清洁", "洗澡", "梳毛", "剪指甲", "刷牙", "耳朵", "眼睛", "皮肤", "毛发", "便便", "行为", "习惯", "社交", "社会化", "指令", "服从", "定点", "排便", "牵引", "笼养", "散养", "丰容", "玩具", "猫砂", "狗粮", "猫粮", "罐头", "冻干", "生骨肉", " aquarium", "鱼缸", "水草", "过滤", "加热", "照明", "水质", "爬宠", "陆龟", "水龟", "蜥蜴", "蛇", "蜘蛛", "仓鼠", "兔子", "鹦鹉", "鸽子"],
        "semantic": ["pet", "animal", "keeping", "care", "training", "medical", "health", "nutrition", "diet", "feeding", "water", "vaccine", "deworming", "check-up", "neutering", "disease", "symptom", "diagnosis", "treatment", "nursing", "rehabilitation", "grooming", "cleaning", "bath", "brushing", "nail clipping", "teeth brushing", "ear", "eye", "skin", "fur", "behavior", "habit", "socialization", "command", "obedience", "toilet training", "leash", "cage", "free range", "enrichment", "toy", "cat litter", "dog food", "cat food", "can", "freeze-dried", "raw food", "aquarium", "fish tank", "aquatic plant", "filter", "heater", "lighting", "water quality", "reptile", "tortoise", "turtle", "lizard", "snake", "spider", "hamster", "rabbit", "parrot", "pigeon"],
        "structure": ["准备-饲养-护理结构", "观察-诊断-干预结构", "训练-互动-社会化结构"],
    },
    {
        "patterns": ["gardening", "horticulture", "园艺", "花艺", "插花", "盆栽", "多肉", "阳台种植", "家庭菜园"],
        "support": ["园艺", "花艺", "插花", "花卉", "植物", "绿植", "盆栽", "盆景", "多肉", "仙人掌", "观叶", "观花", "观果", "香草", "草本", "木本", "藤本", "水生", "土壤", "基质", "肥料", "有机肥", "化肥", "缓释肥", "水溶肥", "浇水", "灌溉", "喷雾", "湿度", "光照", "阳光", "直射", "散射", "温度", "通风", "换盆", "修剪", "整形", "嫁接", "扦插", "播种", "分株", "压条", "孢子", "组培", "病虫害", "防治", "杀菌", "杀虫", "除草", "阳台", "庭院", "屋顶", "室内", "户外", "菜园", "果树", "蔬菜", "家庭菜园", "可食地景"],
        "semantic": ["gardening", "horticulture", "flower arrangement", "floral", "plant", "greenery", "potted plant", "bonsai", "succulent", "cactus", "foliage", "flowering", "fruit", "herb", "herbaceous", "woody", "vine", "aquatic", "soil", "substrate", "fertilizer", "organic fertilizer", "chemical fertilizer", "slow-release", "water-soluble", "watering", "irrigation", "spraying", "humidity", "light", "sunlight", "direct", "diffuse", "temperature", "ventilation", "repotting", "pruning", "shaping", "grafting", "cutting", "sowing", "division", "layering", "spore", "tissue culture", "pest", "disease", "control", "fungicide", "insecticide", "weeding", "balcony", "courtyard", "rooftop", "indoor", "outdoor", "vegetable garden", "fruit tree", "vegetable", "home garden", "edible landscape"],
        "structure": ["选种-培育-养护结构", "环境-水肥-管理结构", "设计-布置-维护结构"],
    },

    # ===== 收藏与鉴赏（2条） =====
    {
        "patterns": ["jewelry", "watchmaking", "珠宝", "钟表", "玉石", "翡翠", "钻石", "鉴定", "拍卖", "收藏"],
        "support": ["珠宝", "首饰", "宝石", "钻石", "红宝", "蓝宝", "祖母绿", "猫眼", "碧玺", "欧泊", "珍珠", "珊瑚", "琥珀", "蜜蜡", "松石", "青金", "玛瑙", "水晶", "玉石", "翡翠", "和田玉", "独山玉", "岫玉", "寿山石", "鸡血石", "田黄", "篆刻", "印章", "印石", "印泥", "钟表", "腕表", "怀表", "座钟", "机芯", "擒纵", "陀飞轮", "万年历", "三问", "计时", "潜水", "天文台", "认证", "品牌", "劳力士", "欧米茄", "百达翡丽", "江诗丹顿", "卡地亚", "鉴定", "评估", "分级", "4C", "GIA", "HRD", "IGI", "国检", "NGTC", "拍卖", "佳士得", "苏富比", "保利", "嘉德", "收藏", "保养", "维修", "翻新"],
        "semantic": ["jewelry", "gem", "diamond", "ruby", "sapphire", "emerald", "cat's eye", "tourmaline", "opal", "pearl", "coral", "amber", "beeswax", "turquoise", "lapis lazuli", "agate", "crystal", "jade", "jadeite", "Hetian jade", "seal cutting", "seal", "ink pad", "watch", "wristwatch", "pocket watch", "mantel clock", "movement", "escapement", "tourbillon", "perpetual calendar", "minute repeater", "chronograph", "diver", "chronometer", "certification", "brand", "Rolex", "Omega", "Patek Philippe", "Vacheron Constantin", "Cartier", "appraisal", "evaluation", "grading", "4C", "GIA", "HRD", "IGI", "NGTC", "auction", "Christie's", "Sotheby's", "Poly", "Guardian", "collection", "maintenance", "repair", "restoration"],
        "structure": ["材质-工艺-鉴定结构", "历史-文化-价值结构", "保养-传承-交易结构"],
    },
    {
        "patterns": ["philately", "collecting", "集邮", "收藏", "钱币", "古董", "文玩", "字画", "瓷器", "青铜器"],
        "support": ["收藏", "集邮", "邮票", "首日封", "极限片", "邮戳", "版式", "齿孔", "背胶", "水印", "荧光", "编号", "小型张", "小全张", "年册", "钱币", "硬币", "纸币", "纪念币", "贵金属", "古钱", "银元", "铜钱", "版别", "品相", "评级", "PMG", "PCGS", "NGC", "古董", "古玩", "文玩", "字画", "书法", "绘画", "国画", "油画", "版画", "瓷器", "陶瓷", "紫砂", "龙泉", "汝窑", "官窑", "定窑", "哥窑", "青铜器", "鼎", "簋", "尊", "盘", "玉器", "家具", "红木", "紫檀", "黄花梨", "金石", "碑帖", "拓片", "古籍", "善本", "版本", "目录", "鉴定", "真伪", "年代", "出处", "传承", "包浆", "皮壳", "修缮", "保养", "展示", "存放"],
        "semantic": ["philately", "stamp collecting", "stamp", "first day cover", "maximum card", "postmark", "format", "perforation", "gum", "watermark", "fluorescence", "number", "souvenir sheet", "miniature sheet", "annual album", "numismatics", "coin", "banknote", "commemorative", "precious metal", "ancient coin", "silver dollar", "copper coin", "variety", "condition", "grading", "PMG", "PCGS", "NGC", "antique", "curio", "cultural plaything", "calligraphy", "painting", "Chinese painting", "oil painting", "print", "porcelain", "ceramic", "zisha", "Longquan", "Ru ware", "Guan ware", "Ding ware", "Ge ware", "bronze ware", "ding", "gui", "zun", "pan", "jade ware", "furniture", "redwood", "rosewood", "Huanghuali", "epigraphy", "rubbing", "ancient book", "rare book", "edition", "catalog", "authentication", "authenticity", "date", "provenance", "patina", "shell", "restoration", "maintenance", "display", "storage"],
        "structure": ["鉴别-分级-保管结构", "研究-整理-展示结构", "传承-交流-交易结构"],
    },

    # ===== 交通与机械文化（2条） =====
    {
        "patterns": ["automotive", "racing", "汽车", "赛车", "改装", "越野", "自驾游", "汽车文化", "F1", "WRC"],
        "support": ["汽车", "赛车", "F1", "WRC", "NASCAR", "拉力", "漂移", "场地", "卡丁", "方程式", "GT", "勒芒", " Indy", "改装", "升级", "动力", "发动机", "涡轮", "机械", "增压", "排气", "进气", "ECU", "刷写", "悬挂", "避震", "刹车", "轮胎", "轮毂", "空力", "包围", "尾翼", "宽体", "姿态", "低趴", "绞牙", "气动", "越野", "四驱", "差速锁", "涉水", "爬坡", "穿越", "自驾", "路线", "攻略", "露营", "床车", "房车", "摩托车", "机车", "巡航", "仿赛", "街车", "踏板", "复古", "文化", "历史", "品牌", "收藏", "模型", "玩具"],
        "semantic": ["automotive", "racing", "F1", "WRC", "NASCAR", "rally", "drifting", "circuit", "karting", "formula", "GT", "Le Mans", "Indy", "modification", "upgrade", "power", "engine", "turbo", "supercharger", "exhaust", "intake", "ECU", "tuning", "suspension", "shock absorber", "brake", "tire", "wheel", "aerodynamics", "body kit", "spoiler", "wide body", "stance", "low", "coilover", "air suspension", "off-road", "4WD", "differential lock", "wading", "climbing", "overland", "self-driving", "route", "guide", "camping", "camper van", "RV", "motorcycle", "cruiser", "sport bike", "street bike", "scooter", "vintage", "culture", "history", "brand", "collection", "model", "toy"],
        "structure": ["理论-实践-调校结构", "路线-准备-执行结构", "欣赏-收藏-分享结构"],
    },
    {
        "patterns": ["aviation", "flight", "航空", "飞行", "民航", "飞行员", "航模", "无人机", "空乘", "机场运营"],
        "support": ["航空", "飞行", "民航", "军用", "通用", "商业", "运输", "货运", "快递", "包机", "公务", "私人", "飞行员", "机长", "副驾驶", "教员", "学员", "执照", "私照", "商照", "仪表", "航线", "多发", "旋翼", "固定翼", "航模", "遥控", "无人机", "DJI", "航拍", "测绘", "巡检", "植保", "救援", "空乘", "乘务", "安全", "服务", "客舱", "机场", "航站楼", "跑道", "塔台", "管制", "签派", "地勤", "机务", "维修", "放行", "适航", "航材", "油料", "配载", "平衡", "气象", "情报", "通告", "航行", "计划", "航路", "导航", "仪表", "着陆", "起飞", "复飞", "备降", "迫降", "紧急"],
        "semantic": ["aviation", "flight", "civil aviation", "military aviation", "general aviation", "commercial", "transport", "cargo", "express", "charter", "business jet", "private jet", "pilot", "captain", "first officer", "instructor", "student", "license", "PPL", "CPL", "instrument rating", "multi-engine", "rotorcraft", "fixed-wing", "model aircraft", "RC", "drone", "UAV", "aerial photography", "surveying", "inspection", "crop spraying", "rescue", "flight attendant", "cabin crew", "safety", "service", "cabin", "airport", "terminal", "runway", "tower", "ATC", "dispatch", "ground handling", "maintenance", "release", "airworthiness", "spare part", "fuel", "load", "balance", "meteorology", "briefing", "NOTAM", "flight plan", "route", "navigation", "instrument", "landing", "takeoff", "go-around", "diversion", "forced landing", "emergency"],
        "structure": ["学习-训练-考核结构", "准备-执行-总结结构", "检查-维护-放行结构"],
    },

    # ===== 表演艺术（2条） =====
    {
        "patterns": ["theater", "drama", "戏剧", "话剧", "音乐剧", "歌剧", "舞剧", "舞台", "表演", "导演", "编剧"],
        "support": ["戏剧", "话剧", "音乐剧", "歌剧", "舞剧", "戏曲", "京剧", "昆曲", "越剧", "黄梅戏", "评剧", "豫剧", "川剧", "粤剧", "秦腔", "梆子", "曲艺", "相声", "小品", "评书", "快板", "大鼓", "舞台", "剧场", "剧院", "排练", "合成", "彩排", "演出", "巡演", "驻演", "商演", "公益", "表演", "演员", "角色", "人物", "塑造", "台词", "唱功", "身段", "武打", "舞蹈", "歌唱", "乐队", "指挥", "导演", "编剧", "剧作", "剧本", "结构", "冲突", "情节", "高潮", "结局", "舞美", "灯光", "音响", "服装", "化妆", "道具", "布景", "装置", "多媒体", "皮影", "木偶", "傩戏"],
        "semantic": ["theater", "drama", "musical", "opera", "dance drama", "Chinese opera", "Peking opera", "Kunqu", "Yue opera", "Huangmei opera", "Ping opera", "Yu opera", "Sichuan opera", "Cantonese opera", "Qinqiang", "clapper opera", "quyi", "crosstalk", "sketch", "storytelling", "clapper talk", "drum", "stage", "theatre", "rehearsal", "synthesis", "dress rehearsal", "performance", "tour", "resident", "commercial", "charity", "actor", "role", "character", "portrayal", "line", "singing", "movement", "martial art", "dance", "vocal", "orchestra", "conductor", "director", "playwright", "script", "structure", "conflict", "plot", "climax", "ending", "stage art", "lighting", "sound", "costume", "makeup", "prop", "scenery", "installation", "multimedia", "shadow puppet", "puppet", "Nuo opera"],
        "structure": ["剧本-排练-演出结构", "角色-行动-冲突结构", "设计-合成-呈现结构"],
    },
    {
        "patterns": ["square dance", "community culture", "广场舞", "社区文化", "秧歌", "腰鼓", "民族舞", "交谊舞"],
        "support": ["广场", "舞", "舞蹈", "健身", "锻炼", "娱乐", "社交", "社区", "文化", "活动", "秧歌", "腰鼓", "扇子", "手绢", "彩带", "民族", "民间", "古典", "现代", "交谊", "国标", "拉丁", "芭蕾", "街舞", "爵士", "肚皮", "印度", "弗拉门戈", "桑巴", "非洲", "鼓", "编排", "教学", "排练", "演出", "比赛", "交流", "协会", "团队", "领队", "教练", "学员", "爱好者", "音乐", "节奏", "步伐", "手势", "表情", "队形", "变换", "服装", "统一", "音响", "功放", "话筒", "场地", "公园", "广场", "小区", "活动", "中心", "文化馆", "老年", "大学"],
        "semantic": ["square dance", "dance", "fitness", "exercise", "entertainment", "social", "community", "culture", "activity", "yangko", "waist drum", "fan", "handkerchief", "ribbon", "folk", "ethnic", "classical", "modern", "ballroom", "standard", "Latin", "ballet", "street dance", "jazz", "belly dance", "Indian dance", "flamenco", "samba", "African dance", "drum", "choreography", "teaching", "rehearsal", "performance", "competition", "exchange", "association", "team", "leader", "coach", "student", "enthusiast", "music", "rhythm", "step", "gesture", "expression", "formation", "transformation", "costume", "uniform", "sound system", "amplifier", "microphone", "venue", "park", "square", "residential area", "activity center", "cultural center", "senior university"],
        "structure": ["学习-排练-表演结构", "个人-团队-社区结构", "音乐-动作-表现结构"],
    },
]


def normalize_goal_input(goal: str | None) -> str:
    return normalize_spaces(str(goal or ""))[:160]


def _extract_goal_phrases(goal: str) -> list[str]:
    normalized_goal = normalize_goal_input(goal)
    phrases = re.split(r"[\n,，;；、|/]+|(?:并且|并|以及|然后|同时|and|then)", normalized_goal)
    return dedupe_terms([phrase for phrase in phrases if len(phrase.strip()) >= 2])


def _extract_emphasized_terms(goal: str) -> list[str]:
    quoted = re.findall(r'[\"“”\'‘’《》【】\[\(](.*?)[\"“”\'‘’》】\]\)]', goal)
    return dedupe_terms(quoted)


def _collect_dynamic_hints(goal: str) -> tuple[list[str], list[str], list[str]]:
    normalized = normalize_text(goal)
    support: list[str] = []
    semantic: list[str] = []
    structure: list[str] = []

    for rule in _DYNAMIC_HINT_RULES:
        if any(pattern in normalized for pattern in rule["patterns"]):
            support.extend(rule["support"])
            semantic.extend(rule["semantic"])
            structure.extend(rule["structure"])

    return dedupe_terms(support), dedupe_terms(semantic), dedupe_terms(structure)


def _filter_negative_terms(goal: str, aliases: list[str], terms: list[str]) -> list[str]:
    goal_haystack = normalize_text(" ".join([goal] + aliases))
    filtered: list[str] = []
    for term in terms:
        normalized = normalize_text(term)
        if not normalized:
            continue
        if normalized in goal_haystack or goal_haystack in normalized:
            continue
        filtered.append(term)
    return dedupe_terms(filtered)


def build_goal_profile(goal: str) -> GoalProfile:
    raw_goal = normalize_goal_input(goal)
    if not raw_goal:
        raise ValueError("missing_goal")

    phrases = _extract_goal_phrases(raw_goal)
    emphasized_terms = _extract_emphasized_terms(raw_goal)
    tokens = dedupe_terms(extract_meaningful_tokens(raw_goal))
    dynamic_support, dynamic_semantic, dynamic_structure = _collect_dynamic_hints(raw_goal)

    aliases = dedupe_terms(emphasized_terms + tokens[:12] + phrases[:6])
    support_keywords = dedupe_terms(_GENERIC_SUPPORT_KEYWORDS + dynamic_support + phrases[:4] + tokens[:6])
    core_keywords = dedupe_terms([raw_goal] + emphasized_terms[:8] + phrases[:8] + tokens[:10] + dynamic_support[:6])
    scene_keywords = dedupe_terms(phrases[1:10] + tokens[10:22] + dynamic_semantic[:8] + dynamic_support[:4])
    semantic_keywords = dedupe_terms(tokens[2:20] + phrases[2:10] + dynamic_semantic[:10] + emphasized_terms[:4])
    structure_patterns = dedupe_terms(_GENERIC_STRUCTURE_HINTS + dynamic_structure)

    strong_negative_keywords = _filter_negative_terms(raw_goal, aliases, _NEGATIVE_KEYWORDS["strong"])
    medium_negative_keywords = _filter_negative_terms(raw_goal, aliases, _NEGATIVE_KEYWORDS["medium"])
    weak_negative_keywords = _filter_negative_terms(raw_goal, aliases, _NEGATIVE_KEYWORDS["weak"])
    negative_keywords = dedupe_terms(strong_negative_keywords + medium_negative_keywords + weak_negative_keywords)
    keywords = dedupe_terms(core_keywords + scene_keywords + support_keywords + semantic_keywords + aliases)

    return GoalProfile(
        raw_goal=raw_goal,
        normalized_goal=normalize_text(raw_goal),
        goal_type="general",
        keywords=keywords,
        negative_keywords=negative_keywords,
        core_keywords=core_keywords,
        scene_keywords=scene_keywords,
        support_keywords=support_keywords,
        semantic_keywords=semantic_keywords,
        structure_patterns=structure_patterns,
        strong_negative_keywords=strong_negative_keywords,
        medium_negative_keywords=medium_negative_keywords,
        weak_negative_keywords=weak_negative_keywords,
        aliases=aliases,
    )
