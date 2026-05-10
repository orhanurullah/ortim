import 'package:flutter/material.dart';

import 'features/foo/foo_page.dart';

void main() {
  runApp(const SampleApp());
}

class SampleApp extends StatelessWidget {
  const SampleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sample',
      home: const FooPage(),
    );
  }
}
