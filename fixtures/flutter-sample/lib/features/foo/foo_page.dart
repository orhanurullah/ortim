import 'package:flutter/material.dart';

import 'foo_controller.dart';

class FooPage extends StatelessWidget {
  const FooPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = FooController();
    return Scaffold(
      appBar: AppBar(title: const Text('Foo')),
      body: Center(child: Text(controller.greeting())),
    );
  }
}
