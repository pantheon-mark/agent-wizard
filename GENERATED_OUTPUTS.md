# Generated Outputs

The Agent Team Wizard is a generator. As an operator runs the wizard, it produces project files for you — foundation documents, agent prompts, scripts, configuration, templates, runtime artifacts, and other content tailored to your specific project.

**You may freely use, modify, copy, publish, sell, sublicense, or relicense the systems, documents, prompts, scripts, project files, and other artifacts the wizard generates for you, with no obligation to attribute the wizard or include the wizard's MIT license notice in the generated outputs.**

This grant is intentionally narrow:

- It applies to wizard-authored template content copied or adapted into your generated project.
- It applies to wizard-authored prompts, scripts, and structural patterns that appear in the generated project.
- It does **not** apply to source files inside the `wizard/` directory itself — those remain MIT-licensed per the LICENSE file.
- It does **not** override licenses for any third-party material, dependencies, services, trademarks, or content you supply or that the wizard pulls from external sources at your direction.
- It does **not** restrict the operator's free choice to license generated outputs however they wish (including more restrictive licenses such as proprietary, source-available, or "all rights reserved").

## Why this exists

MIT license requires the copyright notice to be retained in copies or substantial portions of the licensed software. Without this exception, an operator who used the wizard to build a project and later distributed that project might inherit MIT notice obligations on the wizard-derived template content.

This page makes explicit what the wizard's intent is: **the wizard is a tool for building your software, not a license that follows the software you build.** The MIT license governs the wizard. Your generated project is yours.

## Legal note

This is an explicit additional grant by Mark Tobias (the wizard's copyright holder), not a modification of the MIT License itself. The MIT License continues to govern the wizard's source files in the `wizard/` directory.

If you have questions about applicability to a specific generated artifact, the conservative answer is: subject to the exclusions above, wizard-authored content written into your project directory by the wizard during a wizard session is covered by this grant. Source files inside the wizard's own directory are not.
