"""Small exact-arithmetic capability; never eval, model, filesystem or network.

Only an entire, unambiguous current request is selected. Original decimal
literal text is converted to Fraction, avoiding binary float round-off.
"""
import ast
from decimal import Decimal, localcontext, ROUND_HALF_UP
from fractions import Fraction
import hashlib
import json
import re
import unicodedata

MAX_LENGTH = 256
MAX_NODES = 64
MAX_BITS = 4096
MAX_OUTPUT = 512
ENGINE = 'exact-rational-v1'


class CalculationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise CalculationError(code, message)


def select_request(message):
    """None means ordinary chat. An explicit /计算 stays local on error too."""
    if not isinstance(message, str):
        return None
    text = unicodedata.normalize('NFKC', message).strip()
    explicit = bool(re.match(r'^/(?:计算|calc)(?:\s|$)', text, re.I))
    if explicit:
        text = re.sub(r'^/(?:计算|calc)\s*', '', text, count=1, flags=re.I)
    numeric_only, places = False, None
    for _ in range(2):
        match = re.search(r'(?:[，,。;；]\s*|\s+)?(只(?:需|要)?(?:回答|输出|给出)(?:数字|答案|计算结果|结果)|保留\s*(\d{1,2})\s*位小数)[。.!?？\s]*$', text)
        if not match:
            break
        if match[2] is not None:
            places = int(match[2])
        else:
            numeric_only = True
        text = text[:match.start()].strip()
    text = text.rstrip('。.!?？ \t\r\n')
    prefix = re.match(r'^(?:请\s*)?(?:帮我\s*)?(?:计算(?:一下)?|算一下|算一算|求值|calculate)\s*[:：]?\s*', text, re.I)
    requested = explicit or bool(prefix) or bool(re.search(r'(等于|是多少|得多少|得几|的结果)', text))
    if prefix:
        text = text[prefix.end():]
    text = re.sub(r'(?:等于(?:多少|几|什么)?|是多少|得多少|得几|的结果(?:是什么|是多少)?)$', '', text).strip()
    text = re.sub(r'=\s*$', '', text).strip()
    for source, destination in [('乘以','*'),('除以','/'),('加上','+'),('减去','-'),('加','+'),('减','-'),('乘','*'),('除','/'),('负','-'),('×','*'),('÷','/'),('−','-'),('^','**')]:
        text = text.replace(source, destination)
    for source, destination in [('divided by','/'),('plus','+'),('minus','-'),('times','*')]:
        text = re.sub(r'\b'+source+r'\b', destination, text, flags=re.I)
    if not explicit:
        if not text or len(text) > MAX_LENGTH or not re.fullmatch(r'[0-9.eE+*/()\s-]+', text):
            return None
        if not requested and re.fullmatch(r'\d{2,4}(?:-\d{2,4}){2,}', text):
            return None  # Date/identifier-shaped text is not a calculation.
        try:
            tree = ast.parse(text, mode='eval')
        except (SyntaxError, ValueError, RecursionError):
            return None
        if not any(isinstance(node, ast.BinOp) for node in ast.walk(tree)):
            return None
    return {'expression': text, 'explicit': explicit, 'numeric_only': numeric_only, 'places': places}


def bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
        fail('calculation_limit', '中间结果超过本地计算预算，请缩小算式。')
    return value


def evaluate(expression):
    expression = expression.strip()
    if not expression or len(expression) > MAX_LENGTH or not re.fullmatch(r'[0-9.eE+*/()\s-]+', expression):
        fail('invalid_calculation', '请输入完整算式，仅支持数字、括号、加减乘除和整数次幂。')
    depth = 0
    for char in expression:
        if char == '(':
            depth += 1
            if depth > 16:
                fail('calculation_limit', '括号嵌套超过 16 层。')
        elif char == ')':
            depth -= 1
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        fail('invalid_calculation', '算式格式无效，请检查数字、括号与运算符。')
    if len(list(ast.walk(tree))) > MAX_NODES:
        fail('calculation_limit', '算式步骤过多，请拆分计算。')
    operations = 0
    def visit(node):
        nonlocal operations
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(expression, node)
            if not literal or not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?', literal):
                fail('invalid_calculation', '数字格式不支持。')
            parts = re.split('[eE]', literal)
            if len(re.sub(r'\D', '', parts[0])) > 64 or len(parts) > 1 and abs(int(parts[1])) > 100:
                fail('calculation_limit', '数字长度或科学记数指数超过预算。')
            return bounded(Fraction(Decimal(literal)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            fail('invalid_calculation', '该运算不在本地计算范围内。')
        left, right = visit(node.left), visit(node.right)
        operations += 1
        if isinstance(node.op, ast.Add): value = left + right
        elif isinstance(node.op, ast.Sub): value = left - right
        elif isinstance(node.op, ast.Mult): value = left * right
        elif isinstance(node.op, ast.Div):
            if not right: fail('division_by_zero', '除数不能为零。')
            value = left / right
        else:
            if right.denominator != 1 or abs(right.numerator) > 32:
                fail('calculation_limit', '幂指数必须是 -32 到 32 的整数。')
            if max(left.numerator.bit_length(), left.denominator.bit_length()) * abs(right.numerator) > MAX_BITS:
                fail('calculation_limit', '幂运算超过本地计算预算。')
            if not left and right <= 0:
                fail('invalid_calculation', '本地计算不定义零的零次幂或负次幂。')
            value = left ** right.numerator
        return bounded(value)
    return visit(tree.body), operations


def display(value, places=None):
    if places is not None:
        if not 0 <= places <= 12:
            fail('calculation_limit', '小数位数支持 0 到 12，按四舍五入处理。')
        with localcontext() as ctx:
            ctx.prec = 1300
            text = format((Decimal(value.numerator)/Decimal(value.denominator)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), 'f')
    else:
        denominator, twos, fives = value.denominator, 0, 0
        while denominator % 2 == 0:
            denominator //= 2; twos += 1
        while denominator % 5 == 0:
            denominator //= 5; fives += 1
        if denominator != 1:
            text = str(value.numerator)+'/'+str(value.denominator)
        else:
            digits = max(twos, fives)
            if digits > MAX_OUTPUT:
                fail('calculation_limit', '精确小数超过输出预算，可指定保留小数位数。')
            scaled = value.numerator * 2**(digits-twos) * 5**(digits-fives)
            sign = '-' if scaled < 0 else ''
            raw = str(abs(scaled)).rjust(digits+1, '0')
            text = sign + (raw[:-digits]+'.'+raw[-digits:] if digits else raw)
    if len(text) > MAX_OUTPUT:
        fail('calculation_limit', '结果超过 512 字符的输出预算。')
    return text


def calculate(request):
    expression = request['expression'].strip()
    value, operations = evaluate(expression)
    answer = display(value, request.get('places'))
    receipt = {'schema_version':1,'engine':ENGINE,'expression':expression,
               'exact':{'numerator':str(value.numerator),'denominator':str(value.denominator)},
               'value':answer,'decimal_places':request.get('places'),'rounding':'half_up' if request.get('places') is not None else None,
               'operations':operations,'model_used':False}
    receipt['digest'] = hashlib.sha256(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return answer if request.get('numeric_only') else expression+' = '+answer, receipt
