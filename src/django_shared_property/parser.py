from ast import (
    Add,
    Attribute,
    BinOp,
    Call,
    Compare,
    Constant,
    Eq,
    FunctionDef,
    If,
    Is,
    IsNot,
    List,
    Load,
    Module,
    Name,
    Not,
    Num,
    Return,
    Str,
    UnaryOp,
    arguments,
    fix_missing_locations,
    stmt,
    arg,
)

import six
import astor


class Parser(object):
    def __init__(self, function):
        expression = function(None)
        if getattr(expression, 'copy', None):
            expression = expression.copy()
        func_code = getattr(function, '__code__', None) or function.func_code
        self.file = {
            "lineno": func_code.co_firstlineno,
            "filename": func_code.co_filename,
            "col_offset": 0,
            "ctx": Load(),
        }
        self.expression = expression
        body = self.build_expression(expression)
        if not isinstance(body, stmt):
            body = Return(value=body)
        self.ast = Module(
            body=[
                FunctionDef(
                    name=func_code.co_name,
                    args=arguments(
                        args=[arg(arg='self', annotation=None)],  # function.func_code.co_varnames
                        defaults=[],
                        vararg=None,
                        kwarg=None,
                        kwonlyargs=[],
                        kw_defaults=[],
                        posonlyargs=[],
                    ),
                    kwarg=[],
                    kw_defaults=[],
                    vararg=[],
                    kwonlyargs=[],
                    body=[body],
                    decorator_list=[],
                ),
            ],
            type_ignores=[],
            **self.file
        )
        fix_missing_locations(self.ast)
        print(astor.dump_tree(self.ast))
        # print(astor.to_source(self.ast))
        self.code = compile(self.ast, mode="exec", filename=self.file["filename"])

    def build_expression(self, expression):
        if expression is None:
            return Constant(value=None, **self.file)
        return getattr(self, "handle_{}".format(expression.__class__.__name__.lower()))(expression)

    def handle_case(self, case):
        # We can have N When expressions, and then (optionally) one that is the default.
        return self.handle_when(*case.get_source_expressions())

    def handle_when(self, when, *others):
        test, body = when.get_source_expressions()
        if others:
            if others[0].__class__.__name__ == "When":
                orelse = [self.handle_when(*others)]
            else:
                # Can we ever have other expressions after the default?
                orelse = [Return(value=self.build_expression(others[0]), **self.file)]
        else:
            orelse = []

        return If(
            test=self.build_expression(test),
            body=[Return(value=self.build_expression(body), **self.file)],
            orelse=orelse,
            **self.file
        )

    def handle_q(self, q):
        if not q.children:
            expr = Name(id="True", **self.file)
        elif q.connector == "AND":
            expr = Call(
                func=Name(id="all", **self.file),
                args=[List(elts=[self._attr_lookup(k, v) for k, v in q.children], **self.file)],
                keywords=[],
                kwonlyargs=[],
                **self.file
            )
        else:  # q.connector == 'OR'
            expr = Call(
                func=Name(id="any", **self.file),
                args=[List(elts=[self._attr_lookup(k, v) for k, v in q.children], **self.file)],
                keywords=[],
                kwonlyargs=[],
                **self.file
            )

        if q.negated:
            return UnaryOp(op=Not(), operand=expr, **self.file)

        return expr

    def handle_concat(self, concat):
        return self.build_expression(*concat.get_source_expressions())

    def handle_concatpair(self, pair):
        a, b = pair.get_source_expressions()
        return BinOp(left=self.build_expression(a), op=Add(), right=self.build_expression(b), **self.file)

    def handle_f(self, f):
        # Do we need to use .attname here?
        # What about transforms/lookups?
        f.contains_aggregate = False
        return Attribute(value=Name(id="self", **self.file), attr=f.name, **self.file)

    def handle_value(self, value):
        if isinstance(value.value, six.string_types):
            return Str(s=value.value, **self.file)

        if value.value is None:
            return Constant(value=None, **self.file)

        if isinstance(value.value, int):
            return Num(n=value.value, **self.file)

        if isinstance(value.value, bool):
            return Name(id=str(value.value), **self.file)

        raise ValueError("Unhandled Value")

    def handle_lower(self, lower):
        return Call(
            func=Attribute(value=Name(id="self", **self.file), attr="lower", **self.file),
            args=[],
            keywords=[],
            kwonlyargs=[],
            **self.file
        )

    def handle_expressionwrapper(self, expression):
        return self.build_expression(*expression.get_source_expressions())

    def _attr_lookup(self, attr, value):
        if "__" not in attr:
            return Compare(
                left=Attribute(value=Name(id="self", **self.file), attr=attr, **self.file),
                ops=[Eq()],
                comparators=[self.build_expression(value)],
                **self.file
            )

        attr, lookup = attr.split("__", 1)

        if lookup == "isnull":
            return Compare(
                left=Attribute(value=Name(id="self", **self.file), attr=attr, **self.file),
                ops=[Is() if value else IsNot()],
                comparators=[
                    Constant(value=None, **self.file)
                    # Name(id="None", **self.file)
                ],
                **self.file
            )

        if lookup == "exact":
            return self._attr_lookup(attr, value)

        raise ValueError("Unhandled attr lookup")
