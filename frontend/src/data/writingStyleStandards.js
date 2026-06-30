import { SAMPLE_MICRO_DEMO_LIBRARY } from './sampleMicroDemoCards.js'
import { buildWritingFingerprintSections } from './writingFingerprints.js'

export const WRITING_STYLE_STANDARDS = [
  {
    id: 'realism-ensemble',
    name: '现实主义群像',
    category: '现实 / 群像',
    shortRule: '以人物处境、社会压力和日常细节推动剧情；避免单一主角爽点碾压，让每个关键角色都有自己的利益、难处和选择代价。',
    auditFocus: ['配角是否工具化', '冲突是否来自真实处境', '细节是否有生活质感', '结尾是否避免模板化总结']
  },
  {
    id: 'historical-court',
    name: '历史正剧 / 庙堂',
    category: '历史 / 权谋',
    shortRule: '以制度、信息差、立场和代价构成张力；人物说话要有身份边界，权谋推进应靠证据、误判和政治后果，而不是反派自曝。',
    auditFocus: ['制度逻辑是否自洽', '权谋是否靠信息倾倒', '人物口吻是否符合身份', '历史名词是否滥用']
  },
  {
    id: 'fanren-cultivation',
    name: '凡人流 / 慢热修仙',
    category: '修仙 / 成长',
    shortRule: '主角成长要靠谨慎选择、资源计算和风险承受；升级必须有代价、瓶颈和后果，不要用外挂连续跳级削弱沉浸感。',
    auditFocus: ['资源与等级是否前后一致', '胜负是否有铺垫', '风险是否真实存在', '章节是否过度解释体系']
  },
  {
    id: 'epic-upgrade-fantasy',
    name: '玄幻热血 / 史诗升级',
    category: '玄幻 / 爽文',
    shortRule: '以明确目标、强压迫、升级反馈和阶段爽点驱动阅读；爽点必须来自冲突积累后的释放，不能只靠数值膨胀。',
    auditFocus: ['爽点是否有压迫铺垫', '升级是否有代价', '敌我强弱是否清楚', '结尾钩子是否重复']
  },
  {
    id: 'xianxia-destiny',
    name: '仙侠宿命 / 情绪爆发',
    category: '仙侠 / 宿命',
    shortRule: '以情义、因果、命运选择和牺牲构成章节核心；情绪爆发前必须有克制、误解、残留和不可回避的选择。',
    auditFocus: ['情绪是否像开关', '宿命是否有因果铺垫', '牺牲是否服务人物', '意象是否套话化']
  },
  {
    id: 'light-comedy-contrast',
    name: '轻喜剧 / 反差网感',
    category: '都市 / 喜剧',
    shortRule: '喜剧来自人物误读、身份错位和节奏反差；每个笑点最好同时承担推进、埋梗或暴露关系，杜绝纯段子水文。',
    auditFocus: ['笑点是否推动剧情', '网感是否油腻', '反差是否重复', '严肃线是否被消解']
  },
  {
    id: 'suspense-hook',
    name: '悬疑解谜 / 强钩子',
    category: '悬疑 / 解谜',
    shortRule: '以问题、证据、误导、验证和新问题形成章节链条；关键答案应通过行动和细节揭示，不靠长篇解释。',
    auditFocus: ['线索是否公平', '误导是否合理', '信息是否倾倒', '章尾问题是否有效递进']
  },
  {
    id: 'rational-fantasy',
    name: '知识体系 / 理性奇幻',
    category: '知识 / 奇幻',
    shortRule: '把知识、考据、规则或技术变成行动能力；读者应看到主角如何判断、验证和付出代价，而不是只听解释。',
    auditFocus: ['知识是否参与行动', '术语是否过密', '推理链是否跳跃', '胜负是否靠临时设定']
  },
  {
    id: 'folk-eerie',
    name: '民俗志怪 / 中式诡异',
    category: '民俗 / 志怪',
    shortRule: '以民俗禁忌、地方细节、口耳相传和现实裂缝制造诡异；恐怖感要从生活物件变形中来，不靠堆血腥。',
    auditFocus: ['民俗是否具体', '诡异是否有日常根基', '解释是否过早', '氛围是否只有黑暗沉默']
  },
  {
    id: 'rule-survival',
    name: '规则怪谈 / 无限流 / 生存博弈',
    category: '规则 / 生存',
    shortRule: '规则必须清楚、可验证、可误判；章节推进要靠选择压力和代价，不要靠随机惩罚或作者临时加规则。',
    auditFocus: ['规则是否可执行', '违规后果是否一致', '博弈是否有选择空间', '新规则是否突兀']
  },
  {
    id: 'urban-supernatural',
    name: '都市异能 / 灵气复苏 / 幕后组织',
    category: '都市 / 异能',
    shortRule: '把异常放进现代生活秩序中，让机构、媒体、家庭和工作产生真实反应；异能升级不能脱离社会后果。',
    auditFocus: ['现代秩序是否缺席', '组织行动是否合理', '能力使用是否有代价', '日常与异常是否割裂']
  },
  {
    id: 'female-growth',
    name: '女频成长 / 古言现言 / 逆袭',
    category: '女频 / 成长',
    shortRule: '以关系压力、自我选择和长期成长构成爽点；逆袭不是单纯打脸，而是让角色在资源、认知和情感边界上变强。',
    auditFocus: ['成长是否靠选择', '情感关系是否工具化', '爽点是否只有打脸', '女性角色是否脸谱化']
  },
  {
    id: 'short-drama-reversal',
    name: '短剧爽文 / 强冲突反转',
    category: '短剧 / 强钩子',
    shortRule: '每章要有清晰冲突、快速误会、强反馈和小反转；反转必须服务主线，不要为了刺激牺牲人物逻辑。',
    auditFocus: ['冲突是否快速可见', '反转是否硬拧', '信息是否重复喊口号', '人物行为是否失真']
  },
  {
    id: 'business-healing',
    name: '经营种田 / 美食生活 / 治愈',
    category: '经营 / 治愈',
    shortRule: '用具体经营动作、物品细节和关系变化提供满足感；慢节奏也要有小目标、小反馈和可持续问题。',
    auditFocus: ['经营动作是否具体', '治愈是否空泛', '目标反馈是否明确', '日常细节是否重复']
  }
]

const STANDARD_BY_ID = Object.fromEntries(WRITING_STYLE_STANDARDS.map(item => [item.id, item]))
export const CUSTOM_WRITING_STYLE_STANDARDS_KEY = 'novel_creator_official_writing_standards'
export const USER_FORMAL_WRITING_STANDARDS_KEY = 'novel_creator_user_formal_writing_standards_v2'
export const INACTIVE_SYSTEM_WRITING_STANDARDS_KEY = 'novel_creator_inactive_system_writing_standards_v2'
const FORBIDDEN_PROMPT_KEYS = new Set(['rawExcerpt', 'sourceText', 'sourceCardIds', 'source_card_ids'])
const SAMPLE_SPECIFIC_PROMPT_TOKENS = [
  '凡人修仙传',
  '四世同堂',
  '老舍：四世同堂',
  '一句顶一万句',
  '大奉打更人',
  '修真聊天群',
  '斗破苍穹',
  '全球高武',
  '韩立',
  '黄枫谷',
  '祁家'
]

const SYSTEM_FORMAL_STANDARD_BLUEPRINTS = [
  {
    id: 'system-dialogue-realism',
    name: '对话真实感增强',
    category: '对话 / 关系',
    applicableScenes: '嘴硬关心、旧识旧账、讨价还价、市井闲话、沉默岔开、失败埋怨、亲近废话、恐惧胡扯。',
    match: /嘴硬|旧识|旧账|讨价|市井|闲话|沉默|岔开|埋怨|废话|恐惧|胡扯|对话|dialogue/i,
    principles: [
      '把情绪放进半截话、打岔、转骂物件和答非所问里，避免角色像客服一样交换信息。',
      '熟人旧账要同时露出关系余温，冷嘲和互怼都要带一点没说破的担心。'
    ],
    originalMicroDemo: '门闩又卡住了。阿柳压着嗓子：“这破门真会挑日子。”胖子喘着说：“你想骂就骂，别骂门。”阿柳瞪他：“骂你更没用。”外头脚步声停了，小六赶紧举手：“先别发挥，能不能让锁活到明天？”阿柳咬住半句脏话，把发簪插进锁孔：“闭嘴，给我照光。”',
    antiAiReminder: '只低量参考话缝和打岔的手感，不要把所有角色统一写成冷嘲互怼。',
    notApplicableScenes: '纯动作追逐或无人物互动时不用；不要为了打卡硬塞废话。',
    callStrength: 'low'
  },
  {
    id: 'system-character-humanity',
    name: '人物血肉与情绪反应',
    category: '人物 / 情绪',
    applicableScenes: '人物受伤、隐瞒、误会、亏欠、害怕、嘴硬、关系松动或失衡。',
    match: /人物|情绪|血肉|反应|害怕|误会|隐瞒|亏欠|伤口|嘴硬|关系|配角/i,
    principles: [
      '配角协助主角前先有自己的私心、损失或退路，帮助也要带生活成本。',
      '同一情绪按性格分叉：有人动手，有人沉默，有人照顾别人，有人先算退路。'
    ],
    originalMicroDemo: '船娘听完来意，先把缆绳绕了两圈：“送你们过去可以，回头有人问，我只说载了两袋米。”阿照递钱，她没接：“钱少了。”小芮皱眉：“你刚才还说顺路。”船娘翻白眼：“顺路不顺命。”她一点船篙：“坐船尾，别踩我新补的板。真被追上，你们先跳，我这船还要养家。”',
    antiAiReminder: '私心只用来增加人味，不要把每个配角都写成算计机器。',
    notApplicableScenes: '纯战斗数值或设定表不用；人物反应不能替代主线行动。',
    callStrength: 'low'
  },
  {
    id: 'system-scene-dwell-life-texture',
    name: '场景停留与生活质感',
    category: '场景 / 生活质感',
    applicableScenes: '街巷、店铺、客栈、码头、衙门、饭铺等需要停留感和生活纹理的场景。',
    match: /场景|停留|生活|市井|街|巷|客栈|码头|饭铺|茶馆|秩序|摩擦|微变/i,
    principles: [
      '等待、排队、吃饭、翻找都要有秩序、摩擦和微变，让场景承担观察或关系变化。',
      '生活细节必须改变人物行动、关系或判断，不能只做氛围摆设。'
    ],
    originalMicroDemo: '殿门不开，人群先自己分出几层。带刀的站檐下，挑担的缩在雨边，几个少年挤在石兽旁猜里面出了什么事。阿澈没往前挤，只盯着门槛泥印。卖茶妇人把茶碗一摆，又收了半枚铜钱：“别看正门，正门给人看；侧门才给事走。”',
    antiAiReminder: '场景停留不是延长篇幅；细节不改变判断或关系，就不要加入。',
    notApplicableScenes: '高速打斗和短过场少用；不要用生活细节稀释压力。',
    callStrength: 'low'
  },
  {
    id: 'system-anti-ai-basic',
    name: '反 AI 腔基础标准',
    category: '语言 / 反模板',
    applicableScenes: '任何容易变成剧情摘要、规则清单、功能对白或模板收束的章节。',
    match: /反 AI|AI|模板|清单|摘要|功能|骨架|打卡|anti/i,
    principles: [
      '每章只允许一张微示范作低量手感参照，把提示落实成动作、物件和后果。',
      '出现剧情摘要感时，优先补一个身体反应或关系性废话，再继续推进。'
    ],
    originalMicroDemo: '他想说不疼，袖口却先湿了一圈。小九看见了，没问，只把灯往旁边挪了挪。',
    antiAiReminder: '只低量参考，不在正文复述方法；少用“这意味着”“他意识到”替场景盖章。',
    notApplicableScenes: '后台报告可条目化，正文不按标准打卡；无摘要感时不用硬补。',
    callStrength: 'low'
  },
  {
    id: 'system-popular-story-progression',
    name: '通俗故事推进',
    category: '章节推进 / 通俗可读',
    applicableScenes: '阶段答案、行动后果、线索转向、选择代价和下一章承接。',
    match: /推进|答案|后果|代价|选择|线索|阶段|通俗|故事|开门|悬念/i,
    principles: [
      '追逃或线索循环后先清点损失并交付一个小答案，再让答案带出新代价。',
      '喘息段要承担关系回血或身体代价，不能只是从一个任务跳到下一个任务。'
    ],
    originalMicroDemo: '雨停时，三人躲进废亭。许澈先数箭袋，只剩两支。他把抢来的木牌翻过来，背面刻着一行小字。“不是追我们。”小芮刚松口气，又看见木牌角上沾着熟悉的红蜡。“那追谁？”老秦倒出湿鞋里一粒细砂：“追送牌的人。我们刚好替他把东西带出来了。”亭外的水声忽然显得很近。',
    antiAiReminder: '不要只换地点和追兵制造推进，必须有答案、代价或关系变化。',
    notApplicableScenes: '非追逃、非线索循环、非阶段收束时少用；不要每章都结算。',
    callStrength: 'low'
  },
  {
    id: 'system-natural-setting-exposition',
    name: '设定自然呈现',
    category: '设定 / 信息释放',
    applicableScenes: '规则、组织、功法、制度、物件、地点和势力关系需要进入正文时。',
    match: /设定|规则|组织|制度|功法|物件|钥匙|令牌|信息|呈现|解释|后果/i,
    principles: [
      '新规则先通过操作失败、小代价和旁人后退显形，再补一句短解释。',
      '设定价值通过称呼、排队、价格、让路、物件位置等社会反应呈现。'
    ],
    originalMicroDemo: '银盘亮起时，阿简以为成功了，伸手就按。盘面啪地裂出一道细纹，屋里三个人同时往后退。老师没骂他，只把湿布丢过去：“擦血，别碰第二次。”阿简看见血珠往纹路里渗：“为什么？”老师翻过银盘，露出背面的黑点：“它认的是第一次气息，不认胆子大。”',
    antiAiReminder: '不要一次解释完整规则；先后果，后小结，解释只补最短一口气。',
    notApplicableScenes: '重复设定或读者已懂的规则不用再演；不要用失败示范拖慢动作。',
    callStrength: 'low'
  }
]

const WRITING_GUIDANCE_BY_ID = {
  'realism-ensemble': {
    chapterEngine: '用处境压力、关系变化和现实后果推动章节，不把事件写成单人闯关。',
    characterMethod: '关键角色都带着自己的利益、难处、习惯和小目标进入场景。',
    informationMethod: '信息从生活细节、制度反应、旁人误判和具体后果里露出。',
    proseRhythm: '语言平实克制，长短句自然交替，少用抽象总结收束情绪。',
    endingPreference: '结尾落在关系变化、现实代价或未说出口的选择上。',
    avoid: '避免所有配角只为主角递线索、递情绪或递爽点。'
  },
  'historical-court': {
    chapterEngine: '用制度约束、信息差、立场冲突和政治后果构成章节张力。',
    characterMethod: '人物说话和行动要带身份边界，权力越高越少直白自曝。',
    informationMethod: '证据、文书、礼法、传闻和误判逐层改变局势。',
    proseRhythm: '叙述稳重，少口号，多暗潮；对话留余地，不把权谋讲成说明书。',
    endingPreference: '结尾落在新证据、新立场、新后果或被迫站队上。',
    avoid: '避免反派长篇解释计划，避免用现代口吻替代身份逻辑。'
  },
  'fanren-cultivation': {
    chapterEngine: '用资源计算、风险选择、瓶颈试探和代价承受推动成长。',
    characterMethod: '主角谨慎、会权衡，不轻易相信天降好处；敌友都按利益行动。',
    informationMethod: '修炼规则通过失败、试错、消耗、旁人经验和器物反应展示。',
    proseRhythm: '叙述沉稳，动作和心理都要有因果；不要连续跳级式推进。',
    endingPreference: '结尾落在新风险、新资源缺口、旧债或修炼后遗症上。',
    avoid: '避免外挂连续解决问题，避免升级没有消耗、瓶颈和后果。'
  },
  'epic-upgrade-fantasy': {
    chapterEngine: '用明确目标、强压迫、阶段反馈和冲突释放形成阅读推进。',
    characterMethod: '主角可以强，但强来自积累和选择；对手要有压迫理由。',
    informationMethod: '力量体系通过战斗限制、资源代价、旁观反应和失败边界呈现。',
    proseRhythm: '节奏有推力，但爽点前要有压力蓄积，不能只堆数值。',
    endingPreference: '结尾落在更强阻力、新等级门槛或胜利后代价上。',
    avoid: '避免每章都用同一种震惊、碾压、抬头或握拳结尾。'
  },
  'xianxia-destiny': {
    chapterEngine: '用情义、因果、误解、牺牲和不可回避的选择推动章节。',
    characterMethod: '人物情绪先克制再破裂，选择背后要有旧债、旧诺或旧伤。',
    informationMethod: '宿命和因果通过旧物、誓言、残留、梦境和行动后果慢慢显影。',
    proseRhythm: '语言可有意象，但要落到人物身体和关系，不要空泛抒情。',
    endingPreference: '结尾落在誓言、代价、未完成的告别或命运反扑上。',
    avoid: '避免情绪像开关一样突然爆发，避免牺牲只为煽情。'
  },
  'light-comedy-contrast': {
    chapterEngine: '用身份错位、误读、吐槽节奏和真实压力并行推进。',
    characterMethod: '角色可以好笑，但不能只负责抛梗；每个笑点最好暴露关系或信息。',
    informationMethod: '严肃线藏在玩笑、误读、群聊细节和反差后果里。',
    proseRhythm: '对话快，叙述稳；网感要轻，不要让梗淹没场景。',
    endingPreference: '结尾可用轻微反差、误会升级或严肃信息突然露头。',
    avoid: '避免纯段子水文，避免严肃危机被玩笑完全消解。'
  },
  'suspense-hook': {
    chapterEngine: '用问题、证据、误导、验证和新问题形成章节链条。',
    characterMethod: '人物根据各自知道的信息误判，不要让角色为解释设定而说话。',
    informationMethod: '答案从行动、细节和可回看线索里出现，保持公平误导。',
    proseRhythm: '叙述克制，关键证据具体；不要把所有推理一次讲透。',
    endingPreference: '结尾留下更具体的新问题、反证或被误读的证据。',
    avoid: '避免靠长篇口述揭谜，避免章尾问题只换名字不升级。'
  },
  'rational-fantasy': {
    chapterEngine: '让知识、考据、规则或技术直接改变行动方案和胜负边界。',
    characterMethod: '主角要观察、验证、修正判断，并为判断失误付出代价。',
    informationMethod: '术语必须落在证据、物件反应、实验失败或推理动作里。',
    proseRhythm: '推理段和场景段交替，不要连续堆概念；保留读者自己拼合的空间。',
    endingPreference: '结尾落在一个新证据、新反例或刚被推翻的旧判断上。',
    avoid: '避免知识只作为说明书存在，避免胜负靠临时补设定。'
  },
  'folk-eerie': {
    chapterEngine: '用地方细节、禁忌、传闻和日常物件的轻微变形制造诡异。',
    characterMethod: '人物先按现实经验解释异常，直到解释逐渐失效。',
    informationMethod: '真相从口耳相传、旧物痕迹、地方规矩和反常习惯中渗出。',
    proseRhythm: '语气压低，细节要有湿度、气味和触感，少用空泛黑暗沉默。',
    endingPreference: '结尾落在一个日常物件变得不对、旧规矩被验证或被误解上。',
    avoid: '避免单纯堆血腥和惊吓，避免过早解释诡异来源。'
  },
  'rule-survival': {
    chapterEngine: '规则要可验证、可误判，章节推进靠选择压力和违规代价。',
    characterMethod: '人物在有限信息下试探边界，聪明人也会因为代价和恐惧犯错。',
    informationMethod: '新规则来自观察、失败案例、反证和环境变化，不临时加罚。',
    proseRhythm: '叙述清楚，压力递增；规则文本短而可执行。',
    endingPreference: '结尾落在规则边界被改写、代价到账或新选择出现上。',
    avoid: '避免随机惩罚，避免规则只服务作者想要的反转。'
  },
  'urban-supernatural': {
    chapterEngine: '把异常放进现代生活秩序，让机构、家庭、媒体和工作产生反应。',
    characterMethod: '人物既受超自然牵引，也被现实身份、职业和关系限制。',
    informationMethod: '异常通过监控、报告、谣言、新闻、病例或组织行动露出。',
    proseRhythm: '现实段要有烟火气，异常段要保留秩序崩开的裂缝。',
    endingPreference: '结尾落在异常影响现实秩序，或现实反过来逼迫主角选择。',
    avoid: '避免超能力脱离社会后果，避免组织像背景板一样只发任务。'
  },
  'female-growth': {
    chapterEngine: '用关系压力、自我选择、资源重组和长期成长推进爽点。',
    characterMethod: '主角变强来自认知、边界、资源和情感判断的升级。',
    informationMethod: '关系变化通过对话细节、旧账、新选择和利益交换呈现。',
    proseRhythm: '情绪细腻但不拖沓，爽点应有压抑后的释放和余波。',
    endingPreference: '结尾落在边界重划、关系反转或主角主动选择上。',
    avoid: '避免逆袭只靠打脸，避免女性角色脸谱化或互害工具化。'
  },
  'short-drama-reversal': {
    chapterEngine: '每章保持清晰冲突、快速误会、强反馈和小反转。',
    characterMethod: '人物可以外放，但动机要能被理解，不为反转牺牲逻辑。',
    informationMethod: '关键信息短促抛出，马上造成局势变化。',
    proseRhythm: '节奏快，场景短，反馈明确，但不要每段都喊口号。',
    endingPreference: '结尾落在身份揭示、误会升级或下一轮强冲突入口。',
    avoid: '避免为了刺激让人物行为失真，避免同一反转连续复用。'
  },
  'business-healing': {
    chapterEngine: '用具体经营动作、物品细节、关系变化和小反馈推进。',
    characterMethod: '人物的疲惫、善意、算计和成长都要落在日常动作里。',
    informationMethod: '经营成果通过成本、客人反应、物品变化和关系修复呈现。',
    proseRhythm: '节奏舒缓但有小目标，描写要具体，不空喊治愈。',
    endingPreference: '结尾落在一个小成果、一段关系松动或新的经营难题上。',
    avoid: '避免日常重复同一流程，避免治愈只靠温柔形容词。'
  }
}

function getBrowserStorage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

function cleanText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function safeText(value) {
  if (value == null) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function removeForbiddenPromptTokens(value, extraTokens = []) {
  let text = safeText(value)
  if (!text) return ''
  for (const key of FORBIDDEN_PROMPT_KEYS) {
    text = text.replaceAll(key, '')
  }
  const tokens = [...SAMPLE_SPECIFIC_PROMPT_TOKENS, ...extraTokens]
    .map(item => safeText(item))
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
  for (const token of tokens) {
    text = text.replaceAll(token, '样本原作')
  }
  text = text.replace(/\s+/g, ' ').trim()
  if (text.length > 520) {
    text = `${text.slice(0, 500).replace(/[，。；;,. ]+$/, '')}。`
  }
  return text
}

function normalizeGuidanceObject(guidance = {}, extraTokens = []) {
  const result = {}
  if (!guidance || typeof guidance !== 'object') return result
  Object.entries(guidance).forEach(([key, value]) => {
    if (FORBIDDEN_PROMPT_KEYS.has(key)) return
    if (Array.isArray(value) || (value && typeof value === 'object')) return
    result[key] = removeForbiddenPromptTokens(value, extraTokens)
  })
  return result
}

function normalizeArray(value) {
  return Array.isArray(value) ? value.map(item => safeText(item)).filter(Boolean) : []
}

function normalizeProductStatus(standard = {}) {
  const raw = safeText(standard.status || standard.productStatus).toLowerCase()
  if (standard.active === false || raw === 'inactive' || raw === 'disabled' || raw === '未激活') return 'inactive'
  return 'active'
}

function normalizePrinciples(value, fallback = '') {
  if (Array.isArray(value)) return value.map(item => removeForbiddenPromptTokens(item)).filter(Boolean)
  const text = removeForbiddenPromptTokens(value || fallback)
  return text ? [text] : []
}

function normalizeExperienceCardSnapshot(card = {}) {
  const id = cleanText(card.id || card.cardId)
  const title = removeForbiddenPromptTokens(card.title || card.cardTitle, [card.sourceTitle])
  return {
    id,
    title,
    sourceKind: card.sourceKind || card.source_kind || 'system',
    cardType: card.cardType || card.sampleCardType || card.card_type || '',
    promptReadiness: card.promptReadiness || card.prompt_readiness || '',
    promptInjectionSafeVersion: removeForbiddenPromptTokens(card.promptInjectionSafeVersion || card.chapterSkeleton || card.chapter_skeleton),
    originalMicroDemo: removeForbiddenPromptTokens(card.originalMicroDemo || card.sceneDwell || card.scene_dwell),
    antiSkeletonEffect: removeForbiddenPromptTokens(card.antiSkeletonEffect || card.antiAiNotes || card.anti_ai_notes)
  }
}

function pickCardsForBlueprint(cards = [], blueprint = {}) {
  const usableCards = (cards || []).filter(card => card?.cardId || card?.id)
  const matched = usableCards.filter(card => {
    const text = [
      card.cardTitle,
      card.title,
      card.dialogueType,
      card.promptInjectionSafeVersion,
      card.originalMicroDemo,
      card.antiSkeletonEffect
    ].filter(Boolean).join('\n')
    return blueprint.match?.test(text)
  })
  return (matched.length ? matched : usableCards).slice(0, 4)
}

export function buildSystemWritingStandardsFromExperienceCards(cards = []) {
  return SYSTEM_FORMAL_STANDARD_BLUEPRINTS.map(blueprint => {
    const linkedCards = pickCardsForBlueprint(cards, blueprint)
    const snapshots = linkedCards.map(card => normalizeExperienceCardSnapshot({
      ...card,
      id: `system-card-${card.cardId || card.id}`,
      title: card.cardTitle || card.title,
      sourceKind: 'system'
    }))
    return {
      id: blueprint.id,
      name: blueprint.name,
      category: blueprint.category,
      applicableScenes: blueprint.applicableScenes,
      shortRule: blueprint.principles[0],
      principles: blueprint.principles,
      originalMicroDemo: removeForbiddenPromptTokens(blueprint.originalMicroDemo || snapshots.find(item => item.originalMicroDemo)?.originalMicroDemo),
      antiAiReminder: removeForbiddenPromptTokens(blueprint.antiAiReminder || snapshots.find(item => item.antiSkeletonEffect)?.antiSkeletonEffect),
      notApplicableScenes: blueprint.notApplicableScenes,
      callStrength: blueprint.callStrength,
      linkedExperienceCardIds: snapshots.map(item => item.id).filter(Boolean),
      experienceCardSnapshots: snapshots,
      sourceKind: 'system',
      sourceLabel: '系统内置标准',
      systemBuiltin: true,
      active: true,
      status: 'active',
      noDirectImitation: true,
      auditFocus: ['是否低量调用正式标准', '是否避免复刻经验卡人物、物件、句子', '是否减少功能化对话和剧情摘要'],
      guidance: {
        chapterEngine: blueprint.principles[0],
        dialogueMethod: blueprint.name.includes('对话') ? blueprint.principles[0] : '',
        characterMethod: blueprint.name.includes('人物') ? blueprint.principles[0] : '',
        informationMethod: blueprint.name.includes('设定') ? blueprint.principles[0] : '',
        proseRhythm: blueprint.name.includes('反 AI') ? blueprint.principles[0] : '',
        avoid: blueprint.antiAiReminder
      }
    }
  })
}

export function loadProductFormalWritingStandards(options = {}) {
  const storage = options.storage || getBrowserStorage()
  const inactiveIds = new Set(readStoredList(storage, INACTIVE_SYSTEM_WRITING_STANDARDS_KEY))
  const systemStandards = buildSystemWritingStandardsFromExperienceCards(SAMPLE_MICRO_DEMO_LIBRARY.cards)
    .map(standard => ({
      ...standard,
      active: !inactiveIds.has(standard.id),
      status: inactiveIds.has(standard.id) ? 'inactive' : 'active',
      sourceKind: 'system',
      sourceLabel: '系统内置标准',
      systemBuiltin: true
    }))
  const userStandards = readStoredList(storage, USER_FORMAL_WRITING_STANDARDS_KEY)
    .map(standard => ({
      ...standard,
      sourceKind: standard.sourceKind === 'system' ? 'system' : 'user',
      sourceLabel: standard.sourceKind === 'system' ? '系统内置标准' : '我的写作标准',
      systemBuiltin: standard.sourceKind === 'system'
    }))

  return mergeStandards(systemStandards, userStandards)
    .map(item => {
      try {
        return normalizeBackendWritingStyleStandard(item)
      } catch {
        return null
      }
    })
    .filter(Boolean)
}

function normalizeOptionStandards(options = {}) {
  const list = [
    ...(Array.isArray(options.backendStandards) ? options.backendStandards : []),
    ...(Array.isArray(options.standards) ? options.standards : []),
    ...(Array.isArray(options.extraStandards) ? options.extraStandards : [])
  ]
  return list
    .map(item => {
      try {
        return normalizeBackendWritingStyleStandard(item)
      } catch {
        return null
      }
    })
    .filter(Boolean)
}

function normalizeStandardSnapshots(value = {}) {
  const source = Array.isArray(value)
    ? Object.fromEntries(value.map(item => [item?.id, item]).filter(([id]) => id))
    : (value && typeof value === 'object' ? value : {})
  const result = {}
  Object.entries(source).forEach(([id, item]) => {
    try {
      const normalized = normalizeBackendWritingStyleStandard({ ...item, id: item?.id || id })
      result[normalized.id] = sanitizeWritingStyleStandardForPrompt(normalized)
    } catch {
      // Ignore corrupt snapshots so an old writingProfile does not break the bible page.
    }
  })
  return result
}

function withProfileSnapshots(options = {}, profile = {}) {
  return {
    ...options,
    standardSnapshots: {
      ...(options.standardSnapshots || {}),
      ...(profile?.standardSnapshots || {})
    }
  }
}

function mergeStandards(...groups) {
  const seen = new Set()
  const result = []
  groups.flat().forEach(item => {
    if (!item?.id || seen.has(item.id)) return
    seen.add(item.id)
    result.push(item)
  })
  return result
}

function readStoredList(storage, key) {
  if (!storage?.getItem) return []
  try {
    const raw = storage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeStoredList(storage, key, list) {
  if (!storage?.setItem) return
  storage.setItem(key, JSON.stringify(list))
}

export function normalizeReviewedStandardAsWritingStyleStandard(standard = {}) {
  const guidance = standard.guidance || {}
  const id = cleanText(standard.id)
  const name = cleanText(standard.name)
  if (!id || !name || standard.noDirectImitation !== true) {
    throw new Error('待接入标准缺少名称、ID 或禁止复刻标记')
  }

  return {
    id,
    name,
    category: cleanText(standard.category) || '本地样本 / 人工审核',
    shortRule: removeForbiddenPromptTokens(guidance.chapterEngine) || removeForbiddenPromptTokens(standard.shortRule) || '从本地真人样本抽象出的章节组织方法。',
    auditFocus: Array.isArray(standard.auditFocus) ? standard.auditFocus : [],
    guidance: normalizeGuidanceObject(guidance),
    source: 'reviewed_local_sample',
    custom: true,
    status: 'active',
    auditRequired: false,
    noDirectImitation: true,
    sourceCardIds: Array.isArray(standard.sourceCardIds) ? standard.sourceCardIds.filter(Boolean) : []
  }
}

export function normalizeBackendWritingStyleStandard(standard = {}) {
  const guidance = standard.guidanceJson || standard.guidanceJSON || standard.guidance || {}
  const id = cleanText(standard.id)
  const name = cleanText(standard.name)
  const noDirectImitation = standard.noDirectImitation !== false
  if (!id || !name || !noDirectImitation) {
    throw new Error('后端写作标准缺少名称、ID 或禁止复刻标记')
  }
  const sourceTokens = normalizeArray(standard.forbiddenSourceTitles)
  const normalizedGuidance = normalizeGuidanceObject(guidance, sourceTokens)
  return {
    id,
    name: removeForbiddenPromptTokens(name, sourceTokens),
    category: cleanText(standard.category) || '样本库 / 人工审核',
    shortRule: removeForbiddenPromptTokens(standard.shortRule || normalizedGuidance.chapterEngine, sourceTokens) || '从审核经验卡抽象出的章节组织方法。',
    auditFocus: normalizeArray(standard.auditFocus),
    guidance: normalizedGuidance,
    applicableScenes: removeForbiddenPromptTokens(standard.applicableScenes || guidance.applicableScenes, sourceTokens),
    principles: normalizePrinciples(standard.principles || guidance.principles, normalizedGuidance.characterMethod || normalizedGuidance.chapterEngine || standard.shortRule),
    originalMicroDemo: removeForbiddenPromptTokens(standard.originalMicroDemo || guidance.originalMicroDemo || guidance.microDemo, sourceTokens),
    antiAiReminder: removeForbiddenPromptTokens(standard.antiAiReminder || guidance.antiAiReminder || guidance.avoid || normalizedGuidance.avoid, sourceTokens),
    notApplicableScenes: removeForbiddenPromptTokens(standard.notApplicableScenes || guidance.notApplicableScenes, sourceTokens),
    callStrength: cleanText(standard.callStrength || guidance.callStrength) || 'low',
    linkedExperienceCardIds: normalizeArray(standard.linkedExperienceCardIds || guidance.linkedExperienceCardIds || standard.sourceCardIds),
    experienceCardSnapshots: Array.isArray(standard.experienceCardSnapshots || guidance.experienceCardSnapshots)
      ? (standard.experienceCardSnapshots || guidance.experienceCardSnapshots).map(normalizeExperienceCardSnapshot).filter(item => item.id || item.title)
      : [],
    source: standard.source || 'backend_writing_standard',
    sourceKind: standard.sourceKind || standard.source_kind || (standard.systemBuiltin ? 'system' : 'user'),
    sourceLabel: (standard.sourceKind || standard.source_kind) === 'system' || standard.systemBuiltin ? '系统内置标准' : '我的写作标准',
    custom: !standard.systemBuiltin,
    systemBuiltin: Boolean(standard.systemBuiltin),
    active: normalizeProductStatus(standard) === 'active',
    status: normalizeProductStatus(standard),
    auditRequired: false,
    noDirectImitation: true,
    safetyFlags: normalizeArray(standard.safetyFlags),
    sourceCandidateId: standard.sourceCandidateId || '',
    sourceCardIds: Array.isArray(standard.sourceCardIds) ? standard.sourceCardIds.filter(Boolean) : []
  }
}

export function sanitizeWritingStyleStandardForPrompt(standard = {}) {
  const sourceTokens = normalizeArray(standard.forbiddenSourceTitles)
  const guidance = normalizeGuidanceObject(standard.guidance || standard.guidanceJson || standard.guidanceJSON || {}, sourceTokens)
  const status = normalizeProductStatus(standard)
  return {
    id: cleanText(standard.id),
    name: removeForbiddenPromptTokens(standard.name, sourceTokens),
    category: cleanText(standard.category) || '样本库 / 人工审核',
    shortRule: removeForbiddenPromptTokens(standard.shortRule || guidance.chapterEngine, sourceTokens),
    auditFocus: normalizeArray(standard.auditFocus),
    guidance,
    applicableScenes: removeForbiddenPromptTokens(standard.applicableScenes || guidance.applicableScenes, sourceTokens),
    principles: normalizePrinciples(standard.principles || guidance.principles, guidance.characterMethod || guidance.chapterEngine || standard.shortRule),
    originalMicroDemo: removeForbiddenPromptTokens(standard.originalMicroDemo || guidance.originalMicroDemo || guidance.microDemo, sourceTokens),
    antiAiReminder: removeForbiddenPromptTokens(standard.antiAiReminder || guidance.antiAiReminder || guidance.avoid, sourceTokens),
    notApplicableScenes: removeForbiddenPromptTokens(standard.notApplicableScenes || guidance.notApplicableScenes, sourceTokens),
    callStrength: cleanText(standard.callStrength || guidance.callStrength) || 'low',
    linkedExperienceCardIds: normalizeArray(standard.linkedExperienceCardIds || guidance.linkedExperienceCardIds || standard.sourceCardIds),
    experienceCardSnapshots: Array.isArray(standard.experienceCardSnapshots || guidance.experienceCardSnapshots)
      ? (standard.experienceCardSnapshots || guidance.experienceCardSnapshots).map(normalizeExperienceCardSnapshot).filter(item => item.id || item.title)
      : [],
    source: standard.source || 'prompt_sanitized_standard',
    sourceKind: standard.sourceKind || 'user',
    custom: Boolean(standard.custom),
    active: status === 'active',
    status,
    auditRequired: false,
    noDirectImitation: standard.noDirectImitation !== false,
    safetyFlags: normalizeArray(standard.safetyFlags)
  }
}

export function createWritingProfileStandardSnapshots(profile = {}, standards = []) {
  const ids = selectedWritingStandardIds(profile)
    .map(id => String(id || '').trim())
    .filter(Boolean)
  const byId = Object.fromEntries((standards || []).filter(item => item?.id).map(item => [item.id, item]))
  return ids.reduce((result, id) => {
    const standard = byId[id]
    if (standard) result[id] = sanitizeWritingStyleStandardForPrompt(standard)
    return result
  }, {})
}

export function loadCustomWritingStyleStandards(options = {}) {
  const storage = options.storage || getBrowserStorage()
  return readStoredList(storage, CUSTOM_WRITING_STYLE_STANDARDS_KEY)
    .map(item => {
      try {
        return normalizeReviewedStandardAsWritingStyleStandard(item)
      } catch {
        return null
      }
    })
    .filter(Boolean)
}

export function saveCustomWritingStyleStandard(standard, options = {}) {
  const storage = options.storage || getBrowserStorage()
  const normalized = normalizeReviewedStandardAsWritingStyleStandard(standard)
  const existing = loadCustomWritingStyleStandards({ storage })
  const next = [
    normalized,
    ...existing.filter(item => item.id !== normalized.id)
  ].slice(0, 50)
  writeStoredList(storage, CUSTOM_WRITING_STYLE_STANDARDS_KEY, next)
  return normalized
}

export function getAllWritingStyleStandards(options = {}) {
  return mergeStandards(
    WRITING_STYLE_STANDARDS,
    loadProductFormalWritingStandards(options),
    normalizeOptionStandards(options),
    Object.values(normalizeStandardSnapshots(options.standardSnapshots || {})),
    loadCustomWritingStyleStandards(options)
  )
}

function isFormalWritingStandard(standard = {}) {
  return standard.noDirectImitation === true || standard.id?.startsWith('system-') || Boolean(standard.originalMicroDemo || standard.antiAiReminder || standard.linkedExperienceCardIds?.length)
}

export function getSelectableWritingStyleStandards(options = {}) {
  return getAllWritingStyleStandards(options)
    .filter(isFormalWritingStandard)
    .filter(item => normalizeProductStatus(item) === 'active')
    .map(item => sanitizeWritingStyleStandardForPrompt(item))
}

export function getWritingStyleStandard(id, options = {}) {
  const key = String(id || '').trim()
  if (!key) return null
  if (STANDARD_BY_ID[key]) return STANDARD_BY_ID[key]
  const snapshot = normalizeStandardSnapshots(options.standardSnapshots || {})[key]
  if (snapshot) return snapshot
  return getAllWritingStyleStandards(options).find(item => item.id === key) || null
}

function expandWritingGuidance(standard, guidance = {}) {
  const guidanceOverrides = Object.fromEntries(
    Object.entries(guidance || {}).filter(([, value]) => safeText(value))
  )
  return {
    chapterEngine: standard.shortRule,
    dialogueMethod: '对话要带身份、遮掩、停顿和言外之意，不让角色主动替作者交代设定。',
    characterMethod: '让人物带着自身欲望、压力、误判和小动作进入场景。',
    ensembleMethod: '关键配角至少拥有一个和主角不同的小目标、顾虑或代价。',
    challengeMethod: '任务和关卡要靠选择代价、资源限制、误判后果或规则边界成立。',
    emotionMethod: '情绪先落到动作、身体反应、迟疑和无用细节里，不急着替读者命名。',
    informationMethod: '把信息放进行动、证据、关系变化和具体后果里。',
    proseRhythm: '保持自然叙述节奏，允许长短句和闲笔变化，避免把标准写成逐条打卡。',
    endingPreference: '结尾落在具体变化或下一章可承接的问题上。',
    avoid: '避免机械套用题材标签、模板结尾、角色工具化和说明书式交底。',
    ...guidanceOverrides
  }
}

function getWritingGuidance(standard) {
  if (!standard) {
    return expandWritingGuidance({ shortRule: '' })
  }
  return expandWritingGuidance(standard, standard.guidance || WRITING_GUIDANCE_BY_ID[standard.id])
}

function firstSafeText(values = []) {
  for (const value of values.flat()) {
    const text = removeForbiddenPromptTokens(value)
    if (text) return text
  }
  return ''
}

export function getActiveFormalWritingStandards(standards = []) {
  return (standards || [])
    .map(standard => {
      try {
        return sanitizeWritingStyleStandardForPrompt(standard)
      } catch {
        return null
      }
    })
    .filter(standard => standard?.id && standard.noDirectImitation !== false && standard.status === 'active')
}

export function resolveActiveWritingStandardLowDose(standards = [], context = {}) {
  const activeStandards = getActiveFormalWritingStandards(standards)
  if (!activeStandards.length) return null
  const contextText = [
    context.chapterGoal,
    context.beatPlan,
    context.storyBlock,
    context.blockStageSnapshot,
    context.relationships,
    context.directionReference
  ].map(value => typeof value === 'string' ? value : JSON.stringify(value || '')).join('\n')
  const scored = activeStandards.map((standard, index) => {
    const searchable = [
      standard.name,
      standard.category,
      standard.applicableScenes,
      ...(standard.principles || []),
      standard.shortRule
    ].join('\n')
    const score = searchable
      .split(/[，。；;、\s]+/)
      .filter(part => part.length >= 2 && contextText.includes(part))
      .length
    return { standard, score, index }
  }).sort((left, right) => right.score - left.score || left.index - right.index)
  const standard = scored[0].standard
  const guidance = getWritingGuidance(standard)
  const principle = firstSafeText([
    standard.principles,
    guidance.characterMethod,
    guidance.dialogueMethod,
    guidance.chapterEngine,
    standard.shortRule
  ])
  const originalMicroDemo = firstSafeText([
    standard.originalMicroDemo,
    standard.experienceCardSnapshots?.map(item => item.originalMicroDemo),
    guidance.originalMicroDemo
  ])
  const antiAiReminder = firstSafeText([
    standard.antiAiReminder,
    guidance.antiAiReminder,
    guidance.avoid
  ])
  if (!principle && !originalMicroDemo && !antiAiReminder) return null
  return {
    standardId: standard.id,
    standardName: standard.name,
    principle,
    originalMicroDemo,
    antiAiReminder,
    callStrength: standard.callStrength || 'low'
  }
}

export function formatActiveWritingStandardLowDoseForPrompt(standards = [], context = {}) {
  const resolved = resolveActiveWritingStandardLowDose(standards, context)
  if (!resolved) return ''
  return [
    '## 正式写作标准低量调用',
    '本章只低量参考一条已激活正式写作标准；不要复用经验卡人物、物件、句子，也不要按清单打卡。',
    `- 标准：${resolved.standardName}`,
    resolved.principle ? `- 写法原则：${resolved.principle}` : '',
    resolved.originalMicroDemo ? `- 原创微示范：${resolved.originalMicroDemo}` : '',
    resolved.antiAiReminder ? `- 反 AI 提醒：${resolved.antiAiReminder}` : ''
  ].filter(Boolean).join('\n')
}

function parseMaybeJson(value) {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return {}
  if (!/^[{[]/.test(text)) return value
  try {
    return JSON.parse(text)
  } catch {
    return value
  }
}

function selectedWritingStandardIds(config = {}) {
  if (Array.isArray(config?.selectedStandards)) return config.selectedStandards
  return [
    config?.primaryStandard,
    config?.secondaryFlavor,
    ...(Array.isArray(config?.additionalStandards) ? config.additionalStandards : [])
  ]
}

function normalizeSelectedWritingStandardIds(rawIds = [], lookupOptions = {}, preserveUnknown = false) {
  const ids = []
  for (const rawId of rawIds) {
    const id = String(typeof rawId === 'string' ? rawId : rawId?.id || rawId?.value || '').trim()
    if (!id || ids.includes(id)) continue
    const standard = getWritingStyleStandard(id, lookupOptions)
    if (standard && isFormalWritingStandard(standard) && normalizeProductStatus(standard) === 'active') {
      ids.push(id)
    } else if (!standard && preserveUnknown) {
      ids.push(id)
    }
    if (ids.length >= 3) break
  }
  return ids
}

export function normalizeWritingProfile(value = {}, options = {}) {
  const parsed = parseMaybeJson(value)
  let config = parsed
  const lookupOptions = withProfileSnapshots(options, config)
  const preserveUnknown = options.preserveUnknown === true

  if (Array.isArray(config)) {
    const ids = normalizeSelectedWritingStandardIds(config, lookupOptions, preserveUnknown)
    config = { selectedStandards: ids }
  }

  if (typeof config === 'string') {
    const id = String(config).trim()
    config = getWritingStyleStandard(id, lookupOptions) || preserveUnknown ? { selectedStandards: [id] } : {}
  }

  const selectedIds = normalizeSelectedWritingStandardIds(selectedWritingStandardIds(config), lookupOptions, preserveUnknown)
  const standardSnapshots = normalizeStandardSnapshots(config?.standardSnapshots || {})

  const result = {
    selectedStandards: selectedIds,
    primaryStandard: selectedIds[0] || '',
    secondaryFlavor: selectedIds[1] || '',
    additionalStandards: selectedIds.slice(2),
    customStyleNotes: typeof config?.customStyleNotes === 'string' ? config.customStyleNotes.trim() : ''
  }
  if (Object.keys(standardSnapshots).length) {
    result.standardSnapshots = standardSnapshots
  }
  return result
}

export function getSelectedWritingStyleStandards(config = {}, options = {}) {
  const normalized = normalizeWritingProfile(config, options)
  const lookupOptions = withProfileSnapshots(options, normalized)
  const roleLabels = ['主写作标准', '辅助风味', '补充标准']
  return selectedWritingStandardIds(normalized)
    .map(id => getWritingStyleStandard(id, lookupOptions))
    .filter(standard => standard && isFormalWritingStandard(standard) && normalizeProductStatus(standard) === 'active')
    .slice(0, 3)
    .map((standard, index) => ({ role: roleLabels[index] || '补充标准', standard }))
}

export function getWritingStrategyDisplayCards(config = {}, options = {}) {
  const profile = normalizeWritingProfile(config, options)
  const lookupOptions = withProfileSnapshots(options, profile)
  return getSelectedWritingStyleStandards(profile, lookupOptions).map(({ role, standard }) => {
    const promptStandard = sanitizeWritingStyleStandardForPrompt(standard)
    const guidance = getWritingGuidance(promptStandard)
    const isPrimary = role === '主写作标准'
    return {
      role,
      id: promptStandard.id,
      name: promptStandard.name,
      category: promptStandard.category,
      positioning: isPrimary
        ? '决定本书章节组织、人物方法和叙事气质的主轴。'
        : '只补充局部风味和场景纹理，不推翻主写作标准。',
      note: isPrimary ? profile.customStyleNotes : '',
      sections: buildWritingFingerprintSections(guidance)
    }
  })
}

export function formatWritingStyleStandardsForPrompt(config = {}, options = {}) {
  const profile = normalizeWritingProfile(config, options)
  const lookupOptions = withProfileSnapshots(options, profile)
  const selected = getSelectedWritingStyleStandards(profile, lookupOptions)
  const lowDose = formatActiveWritingStandardLowDoseForPrompt(
    selected.map(({ standard }) => standard),
    options.context || {}
  )
  const blocks = lowDose ? [lowDose] : []

  if (profile.customStyleNotes) {
    blocks.push(`### 项目风格备注\n${profile.customStyleNotes}`)
  }

  if (!blocks.length) return ''

  return blocks.join('\n\n')
}
